"""Convert Logic Pro MIDI exports (assets/music/*.mid) + instruments.toml into driver data (ADR 0005).

    python -m gbtools.music <instruments.toml> <out_dir> <song.mid>...

The Makefile passes the resolved songs (ADR 0007): `rhythmtest_genplaceholder.mid` and `rhythmtest.mid`
are both the song `rhythmtest`.

Outputs in <out_dir>: music.h (song declarations), music_common.c (note table, instruments, waves),
and song_<name>.c per song (banked event streams). Byte layout: src/audio/song.h.
"""

import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import mido

from gbtools.assets import asset_name
from gbtools.errors import ConvertError

FPS = 4194304 / 70224  # Game Boy frame rate, ~59.7275 Hz
BEAT_TICKS = 48
NOTE_BASE = 36  # music_note_freq[0] = C2 on the pulse channels
NOTE_COUNT = 72
WAVE_NOTE_BASE = NOTE_BASE - 12  # the wave channel plays an octave below the pulse table
HITS_MAX = 16
DEFAULT_BPM = 120.0

EV_OFF, EV_INSTR, EV_DUTY, EV_BEND, EV_VIB, EV_TEMPO, EV_LOOP, EV_END, EV_NOP = range(0x80, 0x89)
CC_VIBRATO, CC_DUTY = 1, 12

CHANNELS = ["P1", "P2", "WAVE", "NOISE"]
TRACK_NAMES = CHANNELS + ["HITS"]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SONG_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

# Sort order of events that share a tick: state changes before notes, OFF before a new NOTE.
ORDER_LOOP, ORDER_STATE, ORDER_OFF, ORDER_NOTE, ORDER_END = range(5)


def note_name(n: int) -> str:
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1} ({n})"


def note_freq(index: int) -> int:
    hz = 440.0 * 2 ** ((NOTE_BASE + index - 69) / 12)
    return round(2048 - 131072 / hz)


def tempo_rate(bpm: float) -> int:
    """8.8 fixed-point song ticks per frame."""
    return round(BEAT_TICKS * bpm / 60 / FPS * 256)


# --- instruments -------------------------------------------------------------------------------


@dataclass
class Instrument:
    name: str
    kind: str  # pulse | wave | noise
    duty: int = 0
    env: int = 0
    param: int = 0
    program: int | None = None
    note: int | None = None


@dataclass
class InstrumentSet:
    instruments: list[Instrument]
    waves: list[bytes]

    def index(self, kind: str, program: int) -> int | None:
        for i, ins in enumerate(self.instruments):
            if ins.kind == kind and ins.program == program:
                return i
        return None

    def drum(self, note: int) -> int | None:
        for i, ins in enumerate(self.instruments):
            if ins.kind == "noise" and ins.note == note:
                return i
        return None

    def programs(self, kind: str) -> list[int]:
        return [i.program for i in self.instruments if i.kind == kind]

    def drum_notes(self) -> list[int]:
        return [i.note for i in self.instruments if i.kind == "noise"]


def _int(path, where, entry, key, lo, hi, default=None):
    value = entry.get(key, default)
    if value is None:
        raise ConvertError(path, f"{where}: missing '{key}'")
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ConvertError(path, f"{where}: '{key}' must be an integer {lo}-{hi}, got {value!r}")
    return value


def _env(path, where, entry) -> int:
    pace = _int(path, where, entry, "env_pace", 0, 7, 0)
    direction = entry.get("env_dir", "down")
    if direction not in ("down", "up"):
        raise ConvertError(path, f"{where}: 'env_dir' must be \"down\" or \"up\"")
    return (8 if direction == "up" else 0) | pace


def load_instruments(path: Path) -> InstrumentSet:
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConvertError(path, f"invalid TOML: {e}") from e

    out: list[Instrument] = []
    waves: list[bytes] = []
    for n, entry in enumerate(doc.get("instrument", []), 1):
        name = entry.get("name", f"#{n}")
        where = f"instrument '{name}'"
        kind = entry.get("kind")
        program = _int(path, where, entry, "program", 0, 127)
        if kind == "pulse":
            ins = Instrument(name, kind, duty=_int(path, where, entry, "duty", 0, 3, 2),
                             env=_env(path, where, entry), program=program)
        elif kind == "wave":
            wave = entry.get("wave", "")
            if not re.fullmatch(r"[0-9A-Fa-f]{32}", wave):
                raise ConvertError(path, f"{where}: 'wave' must be exactly 32 hex digits")
            data = bytes.fromhex(wave)
            if data not in waves:
                waves.append(data)
            ins = Instrument(name, kind, param=waves.index(data), program=program)
        else:
            raise ConvertError(path, f"{where}: 'kind' must be \"pulse\" or \"wave\", got {kind!r}")
        if any(o.kind == kind and o.program == program for o in out):
            raise ConvertError(path, f"{where}: another {kind} instrument already uses program {program}")
        out.append(ins)

    for n, entry in enumerate(doc.get("drum", []), 1):
        name = entry.get("name", f"#{n}")
        where = f"drum '{name}'"
        note = _int(path, where, entry, "note", 0, 127)
        env = _env(path, where, entry)
        if env & 7 == 0:
            raise ConvertError(path, f"{where}: drums must decay; set env_pace to 1-7")
        width = entry.get("width", 15)
        if width not in (7, 15):
            raise ConvertError(path, f"{where}: 'width' must be 15 or 7")
        nr43 = (_int(path, where, entry, "shift", 0, 13) << 4) | (8 if width == 7 else 0) \
            | _int(path, where, entry, "divisor", 0, 7)
        if any(o.kind == "noise" and o.note == note for o in out):
            raise ConvertError(path, f"{where}: another drum already uses note {note}")
        out.append(Instrument(name, "noise", env=env, param=nr43, note=note))

    if len(out) > 255:
        raise ConvertError(path, "too many instruments (max 255)")
    return InstrumentSet(out, waves)


# --- songs -------------------------------------------------------------------------------------


@dataclass(order=True)
class Event:
    tick: int
    order: int
    data: bytes = field(compare=False)


@dataclass
class Song:
    name: str
    streams: list[bytes]  # P1, P2, WAVE, NOISE, TEMPO
    rate: int
    bpm: int
    beats_per_bar: int
    hit_instrument: int
    hits: list[int]


@dataclass
class _Timeline:
    ppq: int
    beats_per_bar: int = 4

    def tick(self, midi_ticks: int) -> int:
        return round(midi_ticks * BEAT_TICKS / self.ppq)

    def where(self, track: str, tick: int) -> str:
        bar_ticks = BEAT_TICKS * self.beats_per_bar
        return f"{track} bar {tick // bar_ticks + 1} beat {tick % bar_ticks // BEAT_TICKS + 1}"


def _messages(track):
    t = 0
    for msg in track:
        t += msg.time
        yield t, msg


def _track_name(track) -> str:
    for msg in track:
        if msg.type == "track_name":
            return msg.name.strip()
    return ""


def _channel_events(path, tl, track, name, kind, ins: InstrumentSet) -> tuple[list[Event], dict]:
    """Return events and the per-tick state needed to restore the channel at the loop point."""
    events: list[Event] = []
    program = None
    instr = None
    current = None  # MIDI note currently sounding
    note_on_ticks: set[int] = set()
    state_changes: list[tuple[int, str, int]] = []

    def set_instr(tick):
        nonlocal instr
        p = 0 if program is None else program
        idx = ins.index(kind, p)
        if idx is None:
            have = ", ".join(map(str, ins.programs(kind))) or "none"
            raise ConvertError(path, f"{tl.where(name, tick)}: no {kind} instrument has program {p} "
                                     f"in instruments.toml (defined {kind} programs: {have})")
        if idx != instr:
            instr = idx
            events.append(Event(tick, ORDER_STATE, bytes([EV_INSTR, idx])))
            state_changes.append((tick, "instr", idx))

    for midi_t, msg in _messages(track):
        tick = tl.tick(midi_t)
        if msg.type == "note_on" and msg.velocity > 0:
            if tick in note_on_ticks:
                raise ConvertError(path, f"{tl.where(name, tick)}: two notes start together; Game Boy "
                                         f"channels are monophonic, so move the chord's other notes "
                                         f"to another track or arpeggiate them")
            note_on_ticks.add(tick)
            vol = max(1, round(msg.velocity * 15 / 127))
            if kind == "noise":
                drum = ins.drum(msg.note)
                if drum is None:
                    have = ", ".join(note_name(n) for n in ins.drum_notes()) or "none"
                    raise ConvertError(path, f"{tl.where(name, tick)}: no drum mapped to note "
                                             f"{note_name(msg.note)} (mapped drum notes: {have})")
                events.append(Event(tick, ORDER_NOTE, bytes([drum, vol])))
                continue
            set_instr(tick)
            base = WAVE_NOTE_BASE if kind == "wave" else NOTE_BASE
            index = msg.note - base
            if not 0 <= index < NOTE_COUNT:
                raise ConvertError(path, f"{tl.where(name, tick)}: note {note_name(msg.note)} is outside "
                                         f"the {name} range {note_name(base)}-{note_name(base + NOTE_COUNT - 1)}")
            events.append(Event(tick, ORDER_NOTE, bytes([index, vol])))
            current = msg.note
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            if kind != "noise" and msg.note == current:
                events.append(Event(tick, ORDER_OFF, bytes([EV_OFF])))
                current = None
        elif msg.type == "program_change" and kind != "noise":
            program = msg.program
        elif msg.type == "control_change" and kind != "noise":
            if msg.control == CC_DUTY and kind == "pulse":
                events.append(Event(tick, ORDER_STATE, bytes([EV_DUTY, msg.value >> 5])))
                state_changes.append((tick, "duty", msg.value >> 5))
            elif msg.control == CC_VIBRATO:
                events.append(Event(tick, ORDER_STATE, bytes([EV_VIB, msg.value >> 3])))
                state_changes.append((tick, "vib", msg.value >> 3))
        elif msg.type == "pitchwheel" and kind != "noise":
            bend = max(-64, min(64, round(msg.pitch * 64 / 8192)))
            events.append(Event(tick, ORDER_STATE, bytes([EV_BEND, bend & 0xFF])))
            state_changes.append((tick, "bend", bend))

    # A NOTE retriggers anyway, so drop an OFF that a NOTE on the same tick immediately replaces.
    events.sort()
    pruned = [e for i, e in enumerate(events)
              if not (e.order == ORDER_OFF and i + 1 < len(events)
                      and events[i + 1].tick == e.tick and events[i + 1].order == ORDER_NOTE)]
    return pruned, {"changes": state_changes}


def _state_at(changes, tick) -> list[bytes]:
    """Event bytes that restore instrument/duty/bend/vibrato as they were just before `tick`."""
    state = {}
    for t, key, value in changes:
        if t < tick:
            state[key] = value
    out = []
    if "instr" in state:
        out.append(bytes([EV_INSTR, state["instr"]]))
    if "duty" in state:
        out.append(bytes([EV_DUTY, state["duty"]]))
    out.append(bytes([EV_BEND, state.get("bend", 0) & 0xFF]))
    out.append(bytes([EV_VIB, state.get("vib", 0)]))
    return out


def _encode(events: list[Event]) -> bytes:
    out = bytearray()
    prev = 0
    for e in sorted(events):
        delta = e.tick - prev
        while delta > 255:
            out += bytes([255, EV_NOP])
            delta -= 255
        out.append(delta)
        out += e.data
        prev = e.tick
    return bytes(out)


def _frame(path, tl, name, events, loop_tick, end_tick, restore: list[bytes], off_at_end: bool):
    for e in events:
        if e.tick >= end_tick:
            raise ConvertError(path, f"{tl.where(name, e.tick)}: event after the song end "
                                     f"(bar {end_tick // (BEAT_TICKS * tl.beats_per_bar) + 1}); "
                                     f"move the 'end' marker or trim the region")
    framed = [Event(loop_tick, ORDER_LOOP, bytes([EV_LOOP]))]
    framed += [Event(loop_tick, ORDER_LOOP, b) for b in restore]
    framed += events
    if off_at_end:
        framed.append(Event(end_tick, ORDER_END, bytes([EV_OFF])))
    framed.append(Event(end_tick, ORDER_END + 1, bytes([EV_END])))
    return _encode(framed)


def convert_song(path: Path, ins: InstrumentSet) -> Song:
    name = asset_name(path)
    if not SONG_NAME.match(name):
        raise ConvertError(path, f"song file name '{name}' must be lower_snake_case (it becomes a C name)")
    try:
        mid = mido.MidiFile(path)
    except (OSError, ValueError, EOFError) as e:
        raise ConvertError(path, f"cannot read MIDI file: {e}") from e

    tl = _Timeline(mid.ticks_per_beat)
    tempos: list[tuple[int, float]] = []
    markers: dict[str, int] = {}
    last_tick = 0
    by_name: dict[str, object] = {}
    for track in mid.tracks:
        for midi_t, msg in _messages(track):
            tick = tl.tick(midi_t)
            if msg.type == "set_tempo":
                tempos.append((tick, mido.tempo2bpm(msg.tempo)))
            elif msg.type == "time_signature" and tick == 0:
                tl.beats_per_bar = msg.numerator
            elif msg.type == "marker" and msg.text.strip().lower() in ("loop", "end"):
                markers[msg.text.strip().lower()] = tick
            elif msg.type in ("note_on", "note_off"):
                last_tick = max(last_tick, tick)
        tname = _track_name(track)
        has_notes = any(m.type == "note_on" for m in track)
        if tname.upper() in TRACK_NAMES:
            if tname.upper() in by_name:
                raise ConvertError(path, f"two tracks are named {tname.upper()}")
            by_name[tname.upper()] = track
        elif has_notes:
            raise ConvertError(path, f"track '{tname or '(unnamed)'}' has notes but isn't named one of "
                                     f"{', '.join(TRACK_NAMES)}; rename it in Logic before exporting")

    tempos.sort()
    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, DEFAULT_BPM))
    bar = BEAT_TICKS * tl.beats_per_bar
    loop_tick = markers.get("loop", 0)
    end_tick = markers.get("end", -(-max(last_tick, 1) // bar) * bar)
    if end_tick <= loop_tick:
        raise ConvertError(path, "the 'end' marker must come after the 'loop' marker")

    streams = []
    kinds = {"P1": "pulse", "P2": "pulse", "WAVE": "wave", "NOISE": "noise"}
    for ch in CHANNELS:
        track = by_name.get(ch)
        events, info = _channel_events(path, tl, track, ch, kinds[ch], ins) if track else ([], {"changes": []})
        restore = _state_at(info["changes"], loop_tick) if ch != "NOISE" else []
        streams.append(_frame(path, tl, ch, events, loop_tick, end_tick, restore, ch != "NOISE"))

    tempo_events = [Event(t, ORDER_STATE, bytes([EV_TEMPO]) + tempo_rate(bpm).to_bytes(2, "little"))
                    for t, bpm in tempos if t > 0]
    at_loop = [bpm for t, bpm in tempos if t <= loop_tick][-1]
    loop_tempo = [bytes([EV_TEMPO]) + tempo_rate(at_loop).to_bytes(2, "little")]
    streams.append(_frame(path, tl, "tempo", tempo_events, loop_tick, end_tick, loop_tempo, False))

    hits: list[int] = []
    hit_instrument = next((i for i, x in enumerate(ins.instruments) if x.kind == "pulse"), None)
    if "HITS" in by_name:
        events, info = _channel_events(path, tl, by_name["HITS"], "HITS", "pulse", ins)
        hits = sorted({e.data[0] for e in events if e.order == ORDER_NOTE})
        instrs = [v for _, key, v in info["changes"] if key == "instr"]
        if instrs:
            hit_instrument = instrs[0]
        if len(hits) > HITS_MAX:
            raise ConvertError(path, f"HITS track uses {len(hits)} different pitches (max {HITS_MAX})")
    if hit_instrument is None:
        raise ConvertError(path, "instruments.toml needs at least one pulse instrument")

    return Song(name, streams, tempo_rate(tempos[0][1]), round(tempos[0][1]), tl.beats_per_bar,
                hit_instrument, hits)


# --- C output ----------------------------------------------------------------------------------

BANNER = "/* Generated by tools/gbtools/music.py from assets/music. Do not edit. */\n"


def _bytes_c(data: bytes, indent="    ") -> str:
    rows = [", ".join(f"0x{b:02X}" for b in data[i:i + 16]) for i in range(0, len(data), 16)]
    return "".join(f"{indent}{r},\n" for r in rows)


def render_common(ins: InstrumentSet) -> str:
    kinds = {"pulse": "INSTR_PULSE", "wave": "INSTR_WAVE", "noise": "INSTR_NOISE"}
    freqs = ", ".join(str(note_freq(i)) for i in range(NOTE_COUNT))
    instr = "".join(f"    {{ {kinds[i.kind]}, {i.duty}, 0x{i.env:X}, 0x{i.param:02X} }}, /* {i.name} */\n"
                    for i in ins.instruments)
    waves = "".join("    {\n" + _bytes_c(w, "        ") + "    },\n" for w in ins.waves) \
        or "    { 0 },\n"
    return (BANNER + '#include "audio/song.h"\n\n'
            + f"const uint16_t music_note_freq[NOTE_COUNT] = {{\n    {freqs}\n}};\n\n"
            + "const instrument_t music_instruments[] = {\n" + instr + "};\n\n"
            + "const uint8_t music_waves[][16] = {\n" + waves + "};\n")


def render_song(song: Song) -> str:
    labels = ["p1", "p2", "wave", "noise", "tempo"]
    arrays = "".join(f"static const uint8_t {song.name}_{lab}[] = {{\n{_bytes_c(data)}}};\n\n"
                     for lab, data in zip(labels, song.streams))
    hits = ", ".join(map(str, song.hits)) or "0"
    streams = ", ".join(f"{song.name}_{lab}" for lab in labels)
    return (BANNER + "#pragma bank 255\n\n#include <gbdk/platform.h>\n#include \"audio/song.h\"\n\n"
            + f"BANKREF(song_{song.name})\n\n" + arrays
            + f"const song_t song_{song.name} = {{\n"
            + f"    {{ {streams} }},\n"
            + f"    {song.rate}, {song.bpm}, {song.beats_per_bar}, {song.hit_instrument}, {len(song.hits)},\n"
            + f"    {{ {hits} }},\n}};\n")


def render_header(songs: list[Song]) -> str:
    decls = "".join(f"BANKREF_EXTERN(song_{s.name})\nextern const song_t song_{s.name};\n" for s in songs)
    return (BANNER + "#ifndef GEN_MUSIC_H\n#define GEN_MUSIC_H\n\n#include <gbdk/platform.h>\n"
            + '#include "audio/song.h"\n\n' + decls + "\n#endif\n")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m gbtools.music <instruments.toml> <out_dir> <song.mid>...", file=sys.stderr)
        return 2
    ins_path, out_dir = Path(argv[0]), Path(argv[1])
    try:
        ins = load_instruments(ins_path)
        songs = [convert_song(Path(p), ins) for p in argv[2:]]
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("song_*.c"):
        old.unlink()
    (out_dir / "music.h").write_text(render_header(songs))
    (out_dir / "music_common.c").write_text(render_common(ins))
    for s in songs:
        (out_dir / f"song_{s.name}.c").write_text(render_song(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
