from pathlib import Path

import mido
import pytest

from gbtools import music
from gbtools.errors import ConvertError

REPO = Path(__file__).resolve().parents[2]
PPQ = 96
INSTRUMENTS = """
[[instrument]]
name = "lead"
program = 0
kind = "pulse"
duty = 2
env_pace = 3

[[instrument]]
name = "alt"
program = 5
kind = "pulse"
duty = 1

[[instrument]]
name = "bass"
program = 0
kind = "wave"
wave = "0123456789ABCDEFFEDCBA9876543210"

[[drum]]
name = "kick"
note = 36
shift = 6
divisor = 6
env_pace = 1
"""


@pytest.fixture
def ins(tmp_path):
    p = tmp_path / "instruments.toml"
    p.write_text(INSTRUMENTS)
    return music.load_instruments(p)


def write_midi(tmp_path, tracks, bpm=120, name="song", markers=()):
    """tracks: {name: [(beat, beats_long, note, velocity) | ('pc', beat, program) | ...]}"""
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    now = 0
    for beat, text in sorted(markers):
        conductor.append(mido.MetaMessage("marker", text=text, time=int(beat * PPQ) - now))
        now = int(beat * PPQ)
    mid.tracks.append(conductor)
    for tname, events in tracks.items():
        t = mido.MidiTrack()
        t.append(mido.MetaMessage("track_name", name=tname, time=0))
        msgs = []
        for e in events:
            if e[0] == "pc":
                msgs.append((int(e[1] * PPQ), 0, mido.Message("program_change", program=e[2])))
            elif e[0] == "cc":
                msgs.append((int(e[1] * PPQ), 0, mido.Message("control_change", control=e[2], value=e[3])))
            elif e[0] == "bend":
                msgs.append((int(e[1] * PPQ), 0, mido.Message("pitchwheel", pitch=e[2])))
            else:
                beat, length, note, vel = e
                msgs.append((int(beat * PPQ), 2, mido.Message("note_on", note=note, velocity=vel)))
                msgs.append((int((beat + length) * PPQ), 1, mido.Message("note_off", note=note)))
        now = 0
        for at, _, msg in sorted(msgs, key=lambda m: (m[0], m[1])):
            t.append(msg.copy(time=at - now))
            now = at
        mid.tracks.append(t)
    path = tmp_path / f"{name}.mid"
    mid.save(path)
    return path


def decode(stream: bytes):
    """Turn a stream back into (tick, op, args) tuples, following the layout in src/audio/song.h."""
    sizes = {music.EV_OFF: 0, music.EV_INSTR: 1, music.EV_DUTY: 1, music.EV_BEND: 1, music.EV_VIB: 1,
             music.EV_TEMPO: 3, music.EV_LOOP: 0, music.EV_END: 0, music.EV_NOP: 0}
    out, i, tick = [], 0, stream[0]
    i = 1
    while True:
        op = stream[i]
        n = 1 if op <= 0x7F else sizes[op]
        args = tuple(stream[i + 1:i + 1 + n])
        out.append((tick, op, args))
        i += 1 + n
        if op == music.EV_END:
            return out
        tick += stream[i]
        i += 1


def notes(events):
    return [(t, op, a[0]) for t, op, a in events if op <= 0x7F]


def test_tempo_rate_matches_frame_rate():
    # 128 BPM: 48 * 128 / 60 / 59.7275 = 1.7145 ticks per frame
    assert music.tempo_rate(128) == 439
    assert music.note_freq(69 - music.NOTE_BASE) == 1750  # A4 = 440 Hz


def test_pulse_notes_offs_and_loop_frame(tmp_path, ins):
    path = write_midi(tmp_path, {"P1": [(0, 0.5, 69, 127), (1, 1, 72, 64)]})
    song = music.convert_song(path, ins)
    ev = decode(song.streams[0])
    assert music.EV_LOOP not in [op for _, op, _ in ev]  # a loop at the start needs no LOOP event
    assert notes(ev) == [(0, 69 - 36, 15), (48, 72 - 36, 8)]
    offs = [t for t, op, _ in ev if op == music.EV_OFF]
    assert offs[:2] == [24, 96]
    assert ev[-1] == (192, music.EV_END, ())  # padded to the end of bar 1
    assert song.bpm == 120 and song.beats_per_bar == 4


def test_legato_drops_the_off_that_a_new_note_replaces(tmp_path, ins):
    path = write_midi(tmp_path, {"P1": [(0, 1, 60, 100), (1, 1, 62, 100)]})
    ev = decode(music.convert_song(path, ins).streams[0])
    assert [t for t, op, _ in ev if op == music.EV_OFF] == [96]  # none at the end: the loop's note retriggers


def test_wave_plays_an_octave_below_the_pulse_table(tmp_path, ins):
    path = write_midi(tmp_path, {"WAVE": [(0, 1, 45, 100)]})
    ev = decode(music.convert_song(path, ins).streams[2])
    assert notes(ev)[0][1] == 45 - music.WAVE_NOTE_BASE


def test_program_change_cc_and_bend(tmp_path, ins):
    path = write_midi(tmp_path, {"P1": [("pc", 0, 5), ("cc", 0, 12, 127), ("cc", 0, 1, 64),
                                        ("bend", 0, 8191), (0, 1, 60, 100)]})
    ev = decode(music.convert_song(path, ins).streams[0])
    ops = {op: args for t, op, args in ev if t == 0 and op in
           (music.EV_INSTR, music.EV_DUTY, music.EV_VIB, music.EV_BEND)}
    assert ops[music.EV_INSTR] == (1,)
    assert ops[music.EV_DUTY] == (3,)
    assert ops[music.EV_VIB] == (8,)
    assert ev.index(next(e for e in ev if e[1] == music.EV_INSTR)) < ev.index(notes(ev) and
                                                                            next(e for e in ev if e[1] <= 0x7F))


def test_noise_maps_drum_notes_and_never_cuts(tmp_path, ins):
    path = write_midi(tmp_path, {"NOISE": [(0, 0.25, 36, 127), (1, 0.25, 36, 127)]})
    ev = decode(music.convert_song(path, ins).streams[3])
    drum = next(i for i, x in enumerate(ins.instruments) if x.kind == "noise")
    assert notes(ev) == [(0, drum, 15), (48, drum, 15)]
    assert music.EV_OFF not in [op for _, op, _ in ev]


def test_long_rests_use_nop_padding(tmp_path, ins):
    path = write_midi(tmp_path, {"P1": [(0, 0.5, 60, 100), (12, 0.5, 60, 100)]})
    ev = decode(music.convert_song(path, ins).streams[0])
    assert music.EV_NOP in [op for _, op, _ in ev]
    assert notes(ev)[1][0] == 12 * 48


def test_tempo_changes_and_markers(tmp_path, ins):
    path = write_midi(tmp_path, {"P1": [(0, 1, 60, 100), (6, 1, 60, 100)]},
                      markers=[(4, "loop"), (8, "end")])
    song = music.convert_song(path, ins)
    ev = decode(song.streams[0])
    assert notes(ev)[0][0] == 0  # the intro before the loop marker plays once
    assert (4 * 48, music.EV_LOOP, ()) in ev
    assert ev[-1][0] == 8 * 48
    tempo = decode(song.streams[4])
    assert music.EV_TEMPO not in [op for _, op, _ in tempo]  # constant tempo: nothing to restore


def test_hits_track_sets_pitches_and_instrument(tmp_path, ins):
    path = write_midi(tmp_path, {"HITS": [("pc", 0, 5), (0, 1, 69, 100), (1, 1, 72, 100), (2, 1, 69, 100)]})
    song = music.convert_song(path, ins)
    assert song.hits == [69 - 36, 72 - 36]
    assert song.hit_instrument == 1


@pytest.mark.parametrize("tracks, message", [
    ({"P1": [(0, 1, 60, 100), (0, 1, 64, 100)]}, "P1 bar 1 beat 1: two notes start together"),
    ({"P1": [(0, 1, 20, 100)]}, "outside the P1 range"),
    ({"P1": [("pc", 0, 9), (0, 1, 60, 100)]}, "no pulse instrument has program 9"),
    ({"NOISE": [(0, 1, 40, 100)]}, "no drum mapped to note E2 \\(40\\)"),
    ({"Lead synth": [(0, 1, 60, 100)]}, "track 'Lead synth' has notes but isn't named"),
])
def test_errors_say_where_and_how_to_fix(tmp_path, ins, tracks, message):
    with pytest.raises(ConvertError, match=message):
        music.convert_song(write_midi(tmp_path, tracks), ins)


def test_bad_song_file_name(tmp_path, ins):
    with pytest.raises(ConvertError, match="lower_snake_case"):
        music.convert_song(write_midi(tmp_path, {}, name="My Song"), ins)


def test_instrument_errors(tmp_path):
    p = tmp_path / "instruments.toml"
    p.write_text('[[instrument]]\nname = "x"\nprogram = 0\nkind = "pulse"\nduty = 7\n')
    with pytest.raises(ConvertError, match="instrument 'x': 'duty' must be an integer 0-3"):
        music.load_instruments(p)
    p.write_text('[[drum]]\nname = "k"\nnote = 36\nshift = 1\ndivisor = 1\nenv_pace = 0\n')
    with pytest.raises(ConvertError, match="drums must decay"):
        music.load_instruments(p)


def test_repo_music_converts():
    ins = music.load_instruments(REPO / "assets/music/instruments_genplaceholder.toml")
    for path in (REPO / "assets/music").glob("*_genplaceholder.mid"):
        song = music.convert_song(path, ins)
        assert all(s[-1] == music.EV_END for s in song.streams)


def test_combat_placeholder_changes_tempo_at_bar_5_and_loops_back():
    ins = music.load_instruments(REPO / "assets/music/instruments_genplaceholder.toml")
    song = music.convert_song(REPO / "assets/music/combat_genplaceholder.mid", ins)
    assert song.name == "combat" and song.bpm == 120 and song.beats_per_bar == 4
    tempo = decode(song.streams[4])
    bar = 4 * 48
    changes = [(t, args) for t, op, args in tempo if op == music.EV_TEMPO]
    rate = lambda bpm: tuple(music.tempo_rate(bpm).to_bytes(2, "little")) + (bpm,)  # noqa: E731
    assert changes == [(0, rate(120)), (4 * bar, rate(140))]  # loop restore, then bar 5
    assert tempo[-1] == (8 * bar, music.EV_END, ())
    # Every channel plays, the HITS set rises (hit N of a string plays pitch N) and the hit sound is a pulse.
    assert all(notes(decode(s)) for s in song.streams[:4])
    assert song.hits == sorted(song.hits) and len(song.hits) >= 5
    assert ins.instruments[song.hit_instrument].kind == "pulse"


def test_loop_frame_restores_only_what_the_song_changed(tmp_path, ins):
    """Every event on the loop frame costs ISR time, so restores and OFFs appear only when needed."""
    path = write_midi(tmp_path, {"P1": [(0, 1, 60, 100), ("bend", 6, 4096), (6, 1, 62, 100)],
                                 "P2": [(1, 1, 60, 100)]}, markers=[(4, "loop"), (8, "end")])
    song = music.convert_song(path, ins)
    p1, p2 = decode(song.streams[0]), decode(song.streams[1])
    at_loop = lambda ev: [(op, a) for t, op, a in ev if t == 4 * 48]  # noqa: E731
    assert (music.EV_BEND, (0,)) in at_loop(p1)  # bent after the loop point: restored
    assert [op for op, _ in at_loop(p2)] == [music.EV_LOOP]  # nothing changed: no restores
    tempo = decode(song.streams[4])
    assert music.EV_TEMPO not in [op for _, op, _ in tempo]  # one tempo throughout: song.rate covers it
    # A note on the loop tick retriggers the channel, so the end needs no OFF.
    looped = decode(music.convert_song(write_midi(tmp_path, {"P1": [(0, 1, 60, 100)]}, name="s2"), ins).streams[0])
    assert [t for t, op, _ in looped if op == music.EV_OFF] == [48]
