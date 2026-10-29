"""Sound effects, channel stealing and musical hits, driven through the rhythm-test scene's audition
controls (Left/Right pick an effect, Up plays it, Down switches song) and read back from the APU
registers and the driver's exported state (`_sfx_chan`, `_music_locked`, `_music_clock`)."""

import sys
from pathlib import Path

import pytest

from conftest import boot, enter_scene, press, symbols

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from gbtools import music, sfx  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CH_P1, CH_P2, CH_WAVE, CH_NOISE = range(4)
CHAN_SIZE = 12  # sfx_chan_t (src/audio/sfxdata.h)
NAMES = sorted(sfx.asset_name(p) for p in (REPO / "assets/sfx").glob("*_genplaceholder.toml"))
SLOT = 24 * 256  # one 8th-note step slot in 1/256 ticks (steps_per_beat = 2)
TRIANGLE = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")  # the placeholder songs' bass wave


def effect(name):
    return sfx.load_effect(REPO / f"assets/sfx/{name}_genplaceholder.toml")


class Rom:
    def __init__(self, variant="cgb", sound=True):
        self.pb = boot(variant, sound=sound)
        self.syms = symbols(variant)
        enter_scene(self.pb, "rhythmtest")
        self.pb.tick(30, True)
        self.selected = 0

    def mem(self, sym, n=1):
        a = self.syms[sym]
        return bytes(self.pb.memory[a + i] for i in range(n))

    def chan(self, ch):
        raw = self.mem("_sfx_chan", 4 * CHAN_SIZE)[ch * CHAN_SIZE:(ch + 1) * CHAN_SIZE]
        return {"priority": raw[2], "left": raw[3], "timer": raw[4],
                "freq": raw[6] | raw[7] << 8, "wave": raw[10]}

    def select(self, name):
        target = NAMES.index(name)
        while self.selected != target:
            press(self.pb, "right" if target > self.selected else "left")
            self.pb.tick(1, True)
            self.selected += 1 if target > self.selected else -1

    def play(self, name):
        """Select `name`, then press Up; returns once the effect's first VBlank has run."""
        self.select(name)
        press(self.pb, "up")
        self.pb.tick(1, True)

    def regs(self, ch):
        m = self.pb.memory
        if ch == CH_P1:
            return (m[0xFF10], m[0xFF11] & 0xC0, m[0xFF12], m[0xFF26] & 1)
        if ch == CH_WAVE:
            # While CH3 plays, a CGB read of wave RAM returns the sample byte being played.
            return (m[0xFF1A], m[0xFF1C], m[0xFF26] & 4, m[0xFF30])
        raise ValueError(ch)

    def clock(self):
        b = self.mem("_music_clock", 6)
        return {"beat": b[0] | b[1] << 8, "pos": b[2] << 8 | b[3], "rate": b[4] | b[5] << 8}

    def press_at(self, offset_ticks=0):
        """Press A when the beat position is closest to a step slot + offset. PyBoy's frame boundary
        falls inside the VBlank ISR after the clock has stepped, so the press is judged against the
        position read here."""
        while True:
            c = self.clock()
            d = (c["pos"] - offset_ticks * 256) % SLOT
            if min(d, SLOT - d) <= c["rate"] // 2:
                break
            self.pb.tick(1, False)
        press(self.pb, "a")

    def stop(self):
        self.pb.stop(save=False)


@pytest.fixture
def rom():
    r = Rom()
    yield r
    r.stop()


def run_trace(play: bool, name: str, ch: int, frames: int):
    """The channel's readable registers every frame after `name` is (or, as a control, isn't) played."""
    r = Rom()
    r.select(name)
    if play:
        press(r.pb, "up")
    else:
        r.pb.tick(1, True)
    r.pb.tick(1, True)
    trace, locked = [], []
    for _ in range(frames):
        trace.append(r.regs(ch))
        locked.append(r.mem("_music_locked")[0])
        r.pb.tick(1, True)
    r.stop()
    return trace, locked


def resume_check(name, ch, frames):
    with_sfx, locked = run_trace(True, name, ch, frames)
    control, _ = run_trace(False, name, ch, frames)
    held = [i for i, v in enumerate(locked) if v & (1 << ch)]
    assert held and held[0] == 0, f"{name} never stole channel {ch}"
    release = held[-1] + 1
    assert held == list(range(release)), "the lock must be one unbroken stretch"
    assert release == sum(s[0] for s in effect(name).steps), "the effect lasts the sum of its frames"
    assert with_sfx[:release] != control[:release], "the effect didn't change the channel"
    # The music kept its place while silent: from its first note after the release on, the channel
    # matches a run that never played the effect.
    resumed = next(i for i in range(release, frames) if with_sfx[i:] == control[i:])
    return with_sfx, control, release, resumed


def test_sfx_steals_p1_and_the_music_resumes_on_its_next_note():
    with_sfx, control, release, resumed = resume_check("perfect", CH_P1, 90)
    assert with_sfx[1][1] == 0x40 and with_sfx[1][2] == 0xD0, "perfect starts 25% duty, volume 13"
    assert with_sfx[release][2] == 0, "released channel is silenced"
    assert resumed - release <= 15, "the lead plays 8th notes, so it should be back within one"


def test_wave_sfx_restores_the_music_wave_ram():
    with_sfx, control, release, resumed = resume_check("string_break", CH_WAVE, 160)
    during = {t[3] for t in with_sfx[:release]}
    after = {t[3] for t in with_sfx[resumed:]}
    assert during <= set(effect("string_break").waves[0]), "the effect plays its own wave shape"
    assert after <= set(TRIANGLE) and after - {0x00, 0xFF}, "the music reloaded its wave"


def test_priority_lower_waits_higher_steals(rom):
    rom.play("perfect")
    assert rom.chan(CH_P1)["priority"] == 10
    rom.play("menu_move")  # priority 3: dropped while perfect rings
    assert rom.chan(CH_P1)["priority"] == 10
    rom.play("calib_click")  # priority 12: takes the channel
    c = rom.chan(CH_P1)
    assert c["priority"] == 12 and c["freq"] == sfx.note_period(REPO, "", "C7", "P1")
    rom.pb.tick(5, True)
    assert rom.chan(CH_P1)["priority"] == 0 and rom.mem("_music_locked")[0] == 0


def test_noise_sfx_and_music_share_the_apu(rom):
    rom.play("hit_heavy")
    assert rom.mem("_music_locked")[0] == 1 << CH_NOISE
    assert rom.pb.memory[0xFF22] == 0x20 | 0x08, "NR43: shift 2, 7-bit"
    rom.pb.tick(2, True)
    assert rom.pb.memory[0xFF22] == 0x51, "NR43: shift 5, 15-bit, divisor 1"


def test_musical_hits_rise_with_sfx_hit_step_and_skip_offbeat(rom):
    hits = [music.note_freq(n) for n in rom.mem("_music_hits", rom.mem("_music_hit_count")[0])]
    assert len(hits) == 6
    played = []
    for _ in range(3):  # on-beat presses on consecutive slots: the scene steps sfx_hit_step 0, 1, 2
        rom.press_at(0)
        c = rom.chan(CH_P2)
        assert c["priority"] == 8, "musical hit holds P2 at SFX_HIT_PRIORITY"
        played.append(c["freq"])
        rom.pb.tick(4, True)
    assert played == hits[:3]

    rom.pb.memory[rom.syms["_sfx_hit_step"]] = 2 * len(hits) + 4  # wraps to pitch 4
    rom.press_at(0)
    assert rom.chan(CH_P2)["freq"] == hits[4]
    rom.pb.tick(12, True)

    assert rom.chan(CH_P2)["priority"] == 0
    rom.pb.memory[rom.syms["_tuning"] + 2] = 4  # good_window 4 frames: a clear OFFBEAT margin
    rom.press_at(12)  # halfway between slots, 7 frames from either: OFFBEAT
    rom.pb.tick(1, True)
    assert rom.chan(CH_P2)["priority"] == 0, "OFFBEAT presses play no musical hit"
    rom.pb.tick(3, True)
    rom.press_at(0)
    assert rom.chan(CH_P2)["freq"] == hits[0], "an OFFBEAT press ends the run"


def test_combat_song_changes_tempo_at_bar_5(rom):
    press(rom.pb, "down")
    rom.pb.tick(3, True)
    assert rom.mem("_music_bpm")[0] == 120
    rates = {}
    while True:
        c = rom.clock()
        rates[c["beat"]] = c["rate"]  # the last frame of each beat (a read can land mid-ISR)
        if c["beat"] >= 20:
            break
        rom.pb.tick(1, False)
    assert rates[15] == music.tempo_rate(120)
    assert rates[16] == music.tempo_rate(140) and rom.mem("_music_bpm")[0] == 140
    # Beats keep counting across the change: 4 beats at 140 BPM take ~102 frames.
    frames = 0
    beat = rom.clock()["beat"]
    while rom.clock()["beat"] < beat + 4:
        rom.pb.tick(1, False)
        frames += 1
    assert abs(frames - 4 * 60 / 140 * 59.73) <= 1.5


@pytest.mark.parametrize("variant", ["cgb", "debug", "mine"])
def test_main_loop_never_misses_a_frame_with_sfx_and_hits(variant):
    """Combat song (busier, faster) past its loop point (the heaviest ISR frame), an effect every 9 frames
    on rotating channels and A presses."""
    pb = boot(variant)
    syms = symbols(variant)
    enter_scene(pb, "rhythmtest")
    press(pb, "down")
    pb.tick(2, True)
    frame = [0]
    reached = set()
    pb.hook_register(0, syms["_vsync"], lambda _: reached.add(frame[0]), None)
    for f in range(1000):
        frame[0] = f
        if f % 9 == 0:
            pb.button("up")
        elif f % 9 == 4:
            pb.button("right")
        if f % 13 == 0:
            pb.button("a")
        pb.tick(1, False)
    pb.stop(save=False)
    missed = [f for f in range(120, 1000) if f not in reached]
    assert not missed, f"main loop overran a frame at frames {missed}"
