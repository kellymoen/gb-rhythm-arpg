"""The M2 combat scene (src/scenes/combatflat.c + combat_*.c), headless in PyBoy.

Presses are scripted against the ROM's own beat clock, as in test_calibrate.py: between frames the
test reads _music_clock, works out the step slot and frame error a press made now would be judged
with (beat_judge: 8th-note slots, no latency offset), and holds the button for exactly the frame that
gives the error it wants. Every scripted press is checked against the ROM's own judgement.

The scene's counters live in _combat_stats (src/scenes/combat.h, by byte offset below). Record goldens
after an intended visual change with `UPDATE_GOLDEN=1 make test-rom`, then review them.
"""

import json
import random
import re
import sys
from pathlib import Path

import pytest

from conftest import REPO, ROMS, assert_golden, boot, enter_scene, symbols

sys.path.insert(0, str(REPO / "tools"))
from lab.replay import load_replay, run_replay  # noqa: E402
from lab.symbols import load_symbols  # noqa: E402

BEAT_TICKS = 48
STEPS_PER_BEAT = 2
SLOT_TICKS = BEAT_TICKS // STEPS_PER_BEAT
SETTLE = 40  # frames for the scene to load and its first frames to stream
REPLAYS = Path(__file__).parent / "replays"

# combat_stats_t (src/scenes/combat.h): name -> (offset, size)
STATS = {
    "damage": (0, 2), "dummy_hits": (2, 2), "hits": (4, 1), "last_damage": (5, 1), "finished": (6, 1),
    "finishes": (7, 1), "breaks": (8, 1), "steps": (9, 1), "dodges": (10, 1), "slowmos": (11, 1),
    "strikes": (12, 1), "player_hurts": (13, 1), "strikes_dodged": (14, 1), "last_grade": (15, 1),
    "last_attack": (16, 1), "attacks_started": (17, 1),
}
PLAYER_START_X = 56  # src/scenes/combat.h
DODGE_PX = 16  # player.dodge_px
STRING = {"rush": 0, "pause": 1, "crush": 2, "crush_lunge": 3}  # COMBO_STRING_* (data/combos.toml)
IDLE = 0xFF  # COMBO_IDLE
GRADES = {"OFFBEAT": 0, "GOOD": 1, "PERFECT": 2}
PLAYER_HURT_ACTION = 3  # SPRITE_PLAYER_HURT
SPRITEANIM_ACTION = None  # offset of spriteanim_t.action, found from the DEBUG .cdb (see action_offset)


def judge(beat: int, tick: int, frac: int, rate: int) -> tuple[int | None, int]:
    """beat_judge (src/core/beat.c) at steps_per_beat 2, latency 0: (frames, slot)."""
    if rate == 0:
        return None, 0
    slot = beat * STEPS_PER_BEAT + tick // SLOT_TICKS
    pos = ((tick % SLOT_TICKS) << 8) + frac
    half = SLOT_TICKS << 7
    if pos <= half:
        dist, late = pos, True
    else:
        dist, late, slot = (SLOT_TICKS << 8) - pos, False, slot + 1
    frames = (dist + (rate >> 1)) // rate
    return (frames if late else -frames), slot


def tuning_offsets(variant: str) -> dict[str, int]:
    header = (ROMS[variant].parent / "gen" / "tuning.h").read_text()
    body = header[header.index("typedef struct {") : header.index("} tuning_t;")]
    return {name: 2 * i for i, name in enumerate(re.findall(r"int16_t (\w+);", body))}


def clock_step(beat: int, tick: int, frac: int, rate: int) -> tuple[int, int, int, int]:
    """beat_clock_step (src/core/beat.c): one frame of the beat clock."""
    sub = frac + rate
    t = tick + (sub >> 8)
    return beat + t // BEAT_TICKS, t % BEAT_TICKS, sub & 0xFF, rate


class Driver:
    """Runs a PyBoy one frame at a time with an explicit set of held buttons per frame, and times
    presses from the beat clock. `on_frame(frame, held)` sees every frame's buttons (replay recording).

    The VBlank ISR steps the clock (music_update) and then judges the frame's press (input_poll).
    PyBoy's frame boundary falls at the end of VBlank, so the step normally lands before it and the
    clock read between ticks is the one the next press meets. When the LYC=143 tile-stream interrupt
    delays the ISR, the step can land after the boundary: a hook on beat_clock_step() remembers the
    clock it started from (the clock may even be read half written), and the next press meets that
    clock stepped once."""

    def __init__(self, pb, syms: dict[str, int], tick=None, on_frame=None):
        self.pb, self.syms = pb, syms
        self.tick = tick or (lambda: pb.tick(1, True))
        self.on_frame = on_frame
        self.frame = 0
        self.down: set[str] = set()
        self.judged: list[tuple[int, int]] = []  # (frames, slot) the scripted presses expected
        self.step_from = (-1, None)  # (tick index, clock) of the last beat_clock_step() start
        a = syms["_beat_clock_step"]
        pb.hook_register(a >> 16, a & 0xFFFF, lambda _: setattr(self, "step_from", (self.frame, self.clock())), None)

    def step(self, held=(), n: int = 1) -> None:
        held = set(held)
        for _ in range(n):
            for b in self.down - held:
                self.pb.button_release(b)
            for b in held - self.down:
                self.pb.button_press(b)
            self.down = set(held)
            if self.on_frame:
                self.on_frame(self.frame, frozenset(held))
            self.tick()
            self.frame += 1

    def clock(self) -> tuple[int, int, int, int]:
        m, a = self.pb.memory, self.syms["_music_clock"]
        return m[a] | m[a + 1] << 8, m[a + 2], m[a + 3], m[a + 4] | m[a + 5] << 8

    def press_clock(self) -> tuple[int, int, int, int]:
        """The clock a press held during the next tick is judged at."""
        frame, before = self.step_from
        if frame == self.frame - 1:  # this VBlank's step started (it may be half written): its result
            return clock_step(*before)
        c = self.clock()
        return clock_step(*c) if c[3] else c  # not started yet

    def slot_now(self) -> int:
        return judge(*self.press_clock())[1]

    def tap(self, buttons, slot: int, error: int = 0, hold=(), max_frames: int = 400) -> None:
        """Hold `buttons` (+ `hold`) for the one frame judged `error` frames from step slot `slot`."""
        for _ in range(max_frames):
            frames, s = judge(*self.press_clock())
            if s == slot and frames == error:
                self.judged.append((frames, slot))
                self.step(set(buttons) | set(hold))
                return
            if s > slot or (s == slot and frames is not None and frames > error):
                pytest.fail(f"missed slot {slot} at error {error}: now slot {s} error {frames}")
            self.step(hold)
        pytest.fail(f"slot {slot} never came")

    def play(self, steps: list, first_slot: int, errors=None) -> None:
        """One string: steps like ["a", "a", None, ("b", "right")], one per step slot from first_slot."""
        for k, st in enumerate(steps):
            if st is None:
                continue
            buttons = (st,) if isinstance(st, str) else st
            self.tap(buttons, first_slot + k, errors[k] if errors else 0)


class Combat(Driver):
    """The combat scene, booted and entered, with stats and tuning access."""

    def __init__(self, variant: str = "cgb", pokes: dict[str, int] | None = None):
        pb = boot(variant)
        super().__init__(pb, symbols(variant))
        self.variant = variant
        self.offsets = tuning_offsets(variant)
        self.rom_judged: list[tuple[int, int]] = []
        self.judged_at: list[int] = []  # the frame of every ROM judgement (a press read by the ISR)
        a = self.syms["_beat_judge"]
        pb.hook_register(a >> 16, a & 0xFFFF, lambda _: self.on_judge(), None)
        self.hits: list[tuple[int, int, tuple]] = []  # musical hits: (frame, HITS pitch, clock)
        self.hit_frames: list[tuple[int, tuple]] = []
        a = self.syms["_sfx_hit"]
        pb.hook_register(a >> 16, a & 0xFFFF,
                         lambda _: self.hit_frames.append((self.frame, self.clock())), None)
        self.tick = self.tick_and_read_hits
        enter_scene(pb, "combat")
        for name, value in (pokes or {}).items():
            self.set_tuning(name, value)
        self.step(n=SETTLE)

    def tick_and_read_hits(self) -> None:
        """Tick; if a musical hit started, read its pitch back from the P2 channel it plays on."""
        self.pb.tick(1, True)
        while len(self.hits) < len(self.hit_frames):
            frame, clock = self.hit_frames[len(self.hits)]
            self.hits.append((frame, self.hit_pitch(), clock))

    def hit_pitch(self) -> int:
        m, chan = self.pb.memory, self.syms["_sfx_chan"] + 12  # sfx_chan[CH_P2], 12 bytes each
        assert m[chan + 2] == 8, "no musical hit on P2 (SFX_HIT_PRIORITY)"
        freq = m[chan + 6] | m[chan + 7] << 8
        table = self.syms["_music_note_freq"]
        hits = [m[self.syms["_music_hits"] + i] for i in range(m[self.syms["_music_hit_count"]])]
        return [m[table + 2 * n] | m[table + 2 * n + 1] << 8 for n in hits].index(freq)

    def on_judge(self) -> None:
        self.rom_judged.append(judge(*self.clock()))
        self.judged_at.append(self.frame)

    def set_tuning(self, name: str, value: int) -> None:
        a = self.syms["_tuning"] + self.offsets[name]
        self.pb.memory[a] = value & 0xFF
        self.pb.memory[a + 1] = (value >> 8) & 0xFF

    def stat(self, name: str) -> int:
        off, size = STATS[name]
        a = self.syms["_combat_stats"] + off
        return self.pb.memory[a] | (self.pb.memory[a + 1] << 8 if size == 2 else 0)

    def u8(self, sym: str, off: int = 0) -> int:
        return self.pb.memory[self.syms[sym] + off]

    def approach(self) -> None:
        """Walk from the start to the dummy's left side, level with it, facing it (8 px up, then
        right until its footprint stops the player)."""
        self.step({"up"}, 8)
        self.step({"right"}, 44)
        self.step((), 4)

    def check_judged(self) -> None:
        """Every scripted press was judged by the ROM exactly as the script planned."""
        assert self.rom_judged[-len(self.judged):] == self.judged, "a press landed off its target"

    def stop(self) -> None:
        self.pb.stop(save=False)


def first_free_slot(d: Driver, ahead: int = 2) -> int:
    return d.slot_now() + ahead


# --- strings on the beat -------------------------------------------------------------------------

STRINGS = {
    # name: (steps, damage of each hit at PERFECT)
    "rush": (["a", "a", "a", "a"], [2, 2, 2, 3]),
    "pause": (["a", "a", None, "a"], [2, 2, 8]),
    "crush": (["b", None, "b"], [4, 7]),
    "crush_lunge": (["b", None, ("b", "right")], [4, 7]),
}


@pytest.mark.parametrize("name", list(STRINGS))
def test_string_on_the_beat(name):
    steps, damage = STRINGS[name]
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    c.play(steps, first_free_slot(c))
    c.step(n=40)
    c.check_judged()
    assert c.stat("finished") == STRING[name], f"finished string {c.stat('finished')}"
    assert c.stat("finishes") == 1 and c.stat("breaks") == 0
    assert c.stat("dummy_hits") == len(damage), "not every hit connected"
    assert c.stat("hits") == len(damage)
    assert c.stat("damage") == sum(damage)
    assert c.stat("last_grade") == GRADES["PERFECT"]
    if name in ("rush", "crush_lunge"):
        assert_golden(c.pb, f"combat_{name}_done")
    c.stop()


def test_hit_flash_hitstop_and_popup():
    """The frame after a jab's hit frame: the dummy flashes (OBJ palette 1), a PERFECT popup floats
    over the player, and the counters show the damage."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    c.tap(("a",), first_free_slot(c))
    for _ in range(30):
        c.step()
        if c.stat("dummy_hits"):
            break
    c.step(n=2)
    assert c.stat("dummy_hits") == 1
    oam = [c.pb.memory[0xFE00 + 4 * i : 0xFE00 + 4 * i + 4] for i in range(16, 40)]
    flashed = [o for o in oam if o[0] and 0xA8 <= o[2] < 0xB8 and o[3] & 0x11 == 0x11]
    assert flashed, "dummy parts are not on the flash palette"
    assert c.pb.memory[0xFE00 + 4 * 8] != 0, "no grade popup (OAM 8)"
    assert_golden(c.pb, "combat_hit_flash")
    c.stop()


def test_offbeat_step_does_reduced_damage():
    """Rush with its second hit 7 frames late (OFFBEAT at 120 BPM): it still advances the string and
    finishes it, but deals 2 >> offbeat_damage_shift."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    c.play(["a", "a", "a", "a"], first_free_slot(c), errors=[0, 7, 0, 0])
    c.step(n=40)
    c.check_judged()
    assert c.stat("finished") == STRING["rush"]
    assert c.stat("dummy_hits") == 4
    assert c.stat("damage") == 2 + (2 >> 1) + 2 + 3


def test_string_breaks_after_grace():
    """A A, then nothing: after string_grace (1) empty slot the string breaks; the next A starts a
    new string."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    s = first_free_slot(c)
    c.play(["a", "a"], s)
    # Pause still wants an A at s+3 after its rest; with one grace slot the string waits for s+4
    # and breaks once a press would be judged against s+5.
    while c.slot_now() < s + 5:
        c.step()
    assert c.stat("breaks") == 0, "broke before its grace ran out"
    c.step(n=3)
    assert c.stat("breaks") == 1, "string did not break"
    assert c.stat("finishes") == 0
    c.step(n=4)
    assert_golden(c.pb, "combat_break")
    c.tap(("a",), c.slot_now() + 1)
    c.step(n=12)
    assert c.stat("hits") == 1, "the next press did not start a new string"
    c.check_judged()
    c.stop()


# --- musical hits ----------------------------------------------------------------------------------

DODGE_GRACE = 2  # input.dodge_grace (data/tuning.toml)


def slot_start(slot: int) -> int:
    """Song position of a step slot's start, in 1/256 ticks."""
    return slot * SLOT_TICKS * 256


def position(clock) -> int:
    beat, tick, frac, _rate = clock
    return (beat * BEAT_TICKS + tick) * 256 + frac


def hit_pitches(c: Combat) -> list[int]:
    return [pitch for _frame, pitch, _clock in c.hits]


def test_musical_hits_follow_the_string():
    """Hit N of a string plays HITS pitch N, each on its step slot; an OFFBEAT step plays none but still
    counts (the next hit plays the pitch after it)."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    s = first_free_slot(c)
    c.play(["a", "a", "a", "a"], s, errors=[0, 7, -1, 2])
    c.step(n=20)
    c.check_judged()
    assert c.stat("finished") == STRING["rush"]
    assert hit_pitches(c) == [0, 2, 3]
    for (_frame, _pitch, clock), slot in zip(c.hits, [s, s + 2, s + 3]):
        assert position(clock) >= slot_start(slot), "a hit sounded before its step slot"
    c.stop()


def test_a_dodge_plays_no_hit():
    """A then B within dodge_grace frames, and A+B together: dodges, with no musical hit, also when
    the A was on the beat."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    s = first_free_slot(c)
    c.tap(("a",), s, error=0)
    c.step(("b",))  # B one frame after A: a dodge
    c.step(n=30)
    c.tap(("a",), s + 4, error=-1)
    c.step()
    c.step(("b",))  # two frames after: still a dodge
    c.step(n=30)
    c.tap(("a", "b"), s + 8, error=0)
    c.step(n=30)
    assert c.stat("dodges") == 3 and c.stat("steps") == 0
    assert c.hits == [], f"dodges played musical hits {c.hits}"
    c.stop()


def test_a_press_on_a_taken_slot_plays_no_hit():
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    s = first_free_slot(c)
    c.tap(("a",), s, error=-1)
    c.step(n=3)
    c.tap(("a",), s, error=3)  # judged against the same slot: ignored by the matcher
    c.step(n=30)
    assert c.stat("steps") == 1
    assert hit_pitches(c) == [0]
    c.stop()


def test_a_press_that_breaks_a_string_plays_the_new_strings_first_pitch():
    """A A, then B: B fits no candidate, so Rush breaks and B starts Crush at hit 0."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.approach()
    c.play(["a", "a", "b"], first_free_slot(c))
    c.step(n=30)
    c.check_judged()
    assert c.stat("breaks") == 1
    assert hit_pitches(c) == [0, 1, 0]
    c.stop()


@pytest.mark.parametrize("quantize", [1, 0])
def test_hit_latency(quantize):
    """Frames from the press (the ISR reading it) to its musical hit, for an early, an on-time and a
    late press. A hit waits dodge_grace frames (a dodge must not play one); quantized, an early press
    also waits for its slot's start, and sounds on the first frame at or after it."""
    c = Combat(pokes={"dummy_attack_every_beats": 0, "feedback_quantize_hits": quantize})
    s = first_free_slot(c)
    delays = {}
    for k, (name, error) in enumerate([("early", -5), ("on time", 0), ("late", 4)]):
        slot = s + 6 * k  # far enough apart that each press starts a new string
        c.tap(("a",), slot, error=error)
        c.step(n=20)
        frame, pitch, clock = c.hits[k]
        delays[name] = frame - c.judged_at[-1]
        if quantize and name == "early":
            assert 0 <= position(clock) - slot_start(slot) < clock[3], "not the first frame of the slot"
        assert pitch == 0
    c.check_judged()
    print(f"press -> hit frames (quantize {quantize}): {delays}")
    if quantize:
        assert delays == {"early": 5, "on time": DODGE_GRACE, "late": DODGE_GRACE} or \
            delays == {"early": 6, "on time": DODGE_GRACE, "late": DODGE_GRACE}, delays
    else:
        assert delays == {"early": DODGE_GRACE, "on time": DODGE_GRACE, "late": DODGE_GRACE}, delays
    c.stop()


# --- feel params (data/tuning.toml) ------------------------------------------------------------------

def sfx_ids(variant: str = "cgb") -> dict[str, int]:
    header = (ROMS[variant].parent / "gen" / "sfx.h").read_text()
    return {m[1]: int(m[2]) for m in re.finditer(r"#define SFX_(\w+) (\d+)", header)}


def record_sfx(c: Combat) -> list[int]:
    """Every sfx_play() request from now on (the id is in A)."""
    played: list[int] = []
    a = c.syms["_sfx_play"]
    c.pb.hook_register(a >> 16, a & 0xFFFF, lambda _: played.append(c.pb.register_file.A), None)
    return played


@pytest.mark.parametrize("min_hits,sound", [(2, False), (1, True)])
def test_break_sound_needs_min_hits(min_hits, sound):
    """A lone hit that breaks plays SFX_STRING_BREAK only when feedback.break_sound_min_hits <= 1."""
    c = Combat(pokes={"dummy_attack_every_beats": 0, "feedback_break_sound_min_hits": min_hits})
    played = record_sfx(c)
    s = first_free_slot(c)
    c.tap(("a",), s)
    while c.slot_now() < s + 6:
        c.step()
    c.step(n=4)
    assert c.stat("breaks") == 1
    assert (sfx_ids()["STRING_BREAK"] in played) == sound
    c.stop()


def dash_track(halflife: int) -> list[int]:
    """The player's x (1/16 px) on each of the 12 frames after a dodge (straight back, no target)."""
    c = Combat(pokes={"dummy_attack_every_beats": 0, "player_slide_halflife_ticks": halflife})
    c.tap(("a", "b"), first_free_slot(c), error=5)  # GOOD: no slow-mo
    xs = []
    for _ in range(12):
        c.step()
        xs.append(c.u8("_combat_px") | c.u8("_combat_px", 1) << 8)
    c.stop()
    return xs


def test_dash_eases_out_in_song_ticks():
    """player.slide_halflife_ticks: the dash covers half of what is left every that many song ticks
    (120 BPM: 1.6 ticks per frame). 24 ticks = 15 frames per halving, 2 ticks = about one a frame."""
    start = PLAYER_START_X * 16
    slow, fast = dash_track(24), dash_track(2)
    assert start - fast[-1] == DODGE_PX * 16, "the default dash is over within 12 frames"
    assert start - slow[-1] < DODGE_PX * 16 // 2, "a 24-tick half-life has not halved in 12 frames"
    assert start - slow[-1] >= 0


def popup_rise(rise_ticks: int) -> int:
    """How far the grade popup rose (px) over the 16 frames after it first showed."""
    c = Combat(pokes={"dummy_attack_every_beats": 0, "feedback_popup_rise_ticks": rise_ticks,
                      "feedback_popup_ticks": 96})
    c.tap(("a",), first_free_slot(c))
    while c.pb.memory[0xFE00 + 4 * 8] == 0:
        c.step()
    y0 = c.pb.memory[0xFE00 + 4 * 8]
    c.step(n=16)
    y1 = c.pb.memory[0xFE00 + 4 * 8]
    c.stop()
    return y0 - y1


def test_popup_rises_by_popup_rise_ticks():
    """16 frames at 120 BPM are ~26 song ticks: 3 px at 1 px per 8 ticks, ~13 px at 1 per 2."""
    assert popup_rise(8) in (3, 4)
    assert popup_rise(2) in (12, 13, 14)


def telegraph_frames(blink: int) -> int:
    """Frames the "!" shows during one 48-frame stretch of a telegraph that lasts several beats."""
    c = Combat(pokes={"dummy_attack_every_beats": 0, "dummy_telegraph_blink_ticks": blink})
    c.set_tuning("dummy_telegraph_beats", 8)
    c.set_tuning("dummy_attack_every_beats", 2)
    while not telegraph_shown(c):
        c.step()
    shown = 0
    for _ in range(60):  # two beats at 120 BPM
        c.step()
        shown += telegraph_shown(c)
    c.stop()
    return shown


def test_telegraph_blink_length():
    assert telegraph_frames(48) == 60, "48 ticks: shown the whole beat"
    assert 40 <= telegraph_frames(36) <= 50, "36 ticks: the first 3/4 of each beat"
    assert 12 <= telegraph_frames(12) <= 18, "12 ticks: the first quarter"


# --- dodges and slow-mo ---------------------------------------------------------------------------

def test_perfect_dodge_enters_slowmo():
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.tap(("a", "b"), first_free_slot(c), error=1)
    c.step(n=6)
    c.check_judged()
    assert c.stat("dodges") == 1 and c.stat("slowmos") == 1
    assert c.u8("_combat_slowmo") | c.u8("_combat_slowmo", 1) << 8, "not in slow-mo"
    assert_golden(c.pb, "combat_slowmo")
    # it lasts slowmo.beats (2) beats, then the background comes back
    c.step(n=2 * 30 + 10)
    assert c.u8("_combat_slowmo") == 0 and c.u8("_combat_slowmo", 1) == 0
    c.stop()


def test_late_dodge_does_not_enter_slowmo():
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    c.tap(("a", "b"), first_free_slot(c), error=5)  # GOOD
    c.step(n=6)
    c.check_judged()
    assert c.stat("dodges") == 1 and c.stat("slowmos") == 0
    assert c.u8("_combat_slowmo") == 0
    c.stop()


def test_slowmo_halves_the_dummys_anim_rate():
    """During slow-mo the dummy's anim advances on every enemy_divider-th (2nd) frame only."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    pos = c.syms["_combat_dummy"]  # anim_t.pos follows ends[16] at the start of spriteanim_t.anim
    c.tap(("a", "b"), first_free_slot(c), error=0)
    c.step(n=4)
    assert c.stat("slowmos") == 1
    off = anim_pos_offset()
    before = c.pb.memory[pos + off] | c.pb.memory[pos + off + 1] << 8
    c.step(n=20)
    after = c.pb.memory[pos + off] | c.pb.memory[pos + off + 1] << 8
    ticks = 20 * 1.6  # 120 BPM: 1.6 song ticks per frame
    assert abs((after - before) % 96 - ticks / 2) <= 3, f"dummy anim moved {after - before} ticks in 20 frames"
    c.stop()


def dummy_phase_error(c: Combat) -> int:
    """How far (song ticks) the dummy's looping anim is from where the song says it should be."""
    base, off = c.syms["_combat_dummy"], anim_pos_offset()
    m = c.pb.memory
    pos = m[base + off] | m[base + off + 1] << 8
    count = m[base + off + 2]
    ends = base + off - 32  # anim_t.ends[16] precede pos
    length = m[ends + 2 * (count - 1)] | m[ends + 2 * (count - 1) + 1] << 8
    beat, tick, _frac, _rate = c.clock()
    err = (beat * BEAT_TICKS + tick - pos) % length
    return min(err, length - err)


def test_dummy_is_back_on_the_beat_after_slowmo():
    """During slow-mo the dummy drops half its ticks; when it ends its idle loop restarts in phase."""
    c = Combat(pokes={"dummy_attack_every_beats": 0})
    assert dummy_phase_error(c) <= 2
    c.tap(("a", "b"), first_free_slot(c), error=0)
    c.step(n=4)
    assert c.stat("slowmos") == 1
    c.step(n=20)
    assert dummy_phase_error(c) > 8, "slow-mo should have put the dummy behind"
    while c.u8("_combat_slowmo") | c.u8("_combat_slowmo", 1) << 8:
        c.step()
    c.step(n=6)
    assert dummy_phase_error(c) <= 2, "the dummy stayed off the beat after slow-mo"
    c.stop()


def anim_pos_offset() -> int:
    """Byte offset of spriteanim_t.anim.pos (src/gb/spriteanim.h, src/core/anim.h): 3 pointers, 4
    bytes, then anim_t whose ends[16] (32 bytes) precede pos."""
    return 2 + 2 + 2 + 1 + 1 + 1 + 1 + 32


# --- the dummy's strike ---------------------------------------------------------------------------

def strike_ready(pokes=None) -> Combat:
    """Next to the dummy, then the dummy striking every 2 beats, one beat after its telegraph."""
    c = Combat(pokes={"dummy_attack_every_beats": 0, **(pokes or {})})
    c.approach()
    c.set_tuning("dummy_attack_every_beats", 2)
    c.set_tuning("dummy_telegraph_beats", 1)
    return c


def telegraph_shown(c: Combat) -> bool:
    return c.pb.memory[0xFE00 + 4 * 10] != 0  # "!" on OAM 10


def test_dummy_strike_hurts_an_idle_player_in_range():
    c = strike_ready()
    seen_telegraph = False
    for _ in range(200):
        c.step()
        seen_telegraph |= telegraph_shown(c)
        if c.stat("player_hurts"):
            break
    assert seen_telegraph, "no telegraph before the strike"
    assert c.stat("strikes") == 1 and c.stat("player_hurts") == 1
    c.step(n=3)
    assert c.u8("_combat_player", action_offset()) == PLAYER_HURT_ACTION, "player not in the hurt anim"
    assert_golden(c.pb, "combat_player_hurt")
    c.stop()


def test_dummy_strike_misses_a_player_out_of_range():
    c = Combat(pokes={"dummy_attack_every_beats": 2, "dummy_telegraph_beats": 1})
    for _ in range(150):  # from the start position the dummy is out of reach
        c.step()
    assert c.stat("strikes") >= 1 and c.stat("player_hurts") == 0
    c.stop()


@pytest.mark.parametrize("error", [-2, 3, 6])
def test_dodging_on_the_strike_beat_avoids_it(error):
    """A dodge 2 frames early (dodging when the strike lands) or 3 or 6 (good_window) frames late
    (inside the strike's grace) avoids the strike."""
    c = strike_ready()
    while not telegraph_shown(c):
        c.step()
    beat = c.clock()[0]
    c.tap(("a", "b"), (beat + 1) * STEPS_PER_BEAT, error)
    c.step(n=20)
    c.check_judged()
    assert c.stat("strikes") == 1 and c.stat("strikes_dodged") == 1
    assert c.stat("player_hurts") == 0
    assert c.stat("slowmos") == (1 if abs(error) <= 3 else 0)  # PERFECT dodges start slow-mo
    c.stop()


VSYNC = "f040e680c8afe0917600f091b728f9c9"  # GBDK's wait_vbl_done; its `ret` is at +15


def run_main_loop_at_30fps(c: Combat) -> None:
    """Every other vsync() waits for one more VBlank: the scene's loop runs at 30 fps while the
    VBlank ISR (beat clock, input, sound) still runs at 60."""
    v = c.syms["_vsync"]
    assert bytes(c.pb.memory[v + i] for i in range(16)).hex() == VSYNC, "GBDK's vsync() changed"
    calls = [0]

    def wait_again(_):
        calls[0] += 1
        if calls[0] & 1:
            c.pb.register_file.PC = v + 5  # back to `xor a; ldh (_vbl_done), a; halt`

    c.pb.hook_register(0, v + 15, wait_again, None)


@pytest.mark.parametrize("error,hurt", [(3, False), (6, False), (7, True)])
def test_strike_grace_is_counted_in_vblanks(error, hurt):
    """With the main loop at 30 fps, a late dodge still has to come within good_window (6) frames of
    the strike's beat: the grace is counted in VBlanks, not in main-loop passes."""
    c = strike_ready()
    run_main_loop_at_30fps(c)
    while not telegraph_shown(c):
        c.step()
    beat = c.clock()[0]
    c.tap(("a", "b"), (beat + 1) * STEPS_PER_BEAT, error)
    c.step(n=30)
    c.check_judged()
    assert c.stat("strikes") == 1 and c.stat("dodges") == 1
    assert c.stat("player_hurts") == (1 if hurt else 0)
    assert c.stat("strikes_dodged") == (0 if hurt else 1)
    c.stop()


def action_offset() -> int:
    """Byte offset of spriteanim_t.action: after the init fields (sprite, anim_banks, anims: 3
    pointers; action_count, bank, tile, slot_tiles) and anim_t (ends[16], pos, 8 bytes)."""
    return 6 + 4 + 32 + 2 + 8


# --- frame budget ---------------------------------------------------------------------------------

@pytest.mark.parametrize("variant", ["cgb", "dmg", "mine"])
def test_main_loop_never_misses_a_frame(variant):
    """1500 frames of button spam (attacks, dodges, walking; the dummy striking every 4 beats) past
    the song's tempo change (bar 5) and its loop point (~890 frames). The main loop must call
    vsync() on every frame."""
    c = Combat(variant, pokes={"dummy_attack_every_beats": 4})
    reached = set()
    c.pb.hook_register(0, c.syms["_vsync"], lambda _: reached.add(c.frame), None)
    rng = random.Random(7)
    start, held = c.frame, set()
    for _ in range(1500):
        p = rng.random()
        press = {rng.choice(["a", "b"])} if p < 0.25 else {"a", "b"} if p < 0.28 else set()
        if rng.random() < 0.05:
            held = set(rng.sample(["up", "down", "left", "right"], rng.choice([0, 1, 1, 2])))
            held -= {"up"} if "down" in held else set()
            held -= {"left"} if "right" in held else set()
        c.step(held | press)
    stats = {k: c.stat(k) for k in ("steps", "dodges", "dummy_hits", "strikes")}
    c.stop()
    missed = [f for f in range(start + 2, c.frame) if f not in reached]
    assert not missed, f"main loop overran a frame at frames {missed[:20]} ({len(missed)} in all)"
    assert stats["steps"] > 50 and stats["dodges"] > 5 and stats["strikes"] >= 1, stats


# --- replays (feel regressions) ---------------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(REPLAYS.glob("combat_*.json")), ids=lambda p: p.stem)
def test_replay(path):
    """Replays recorded on the placeholders-only DEBUG ROM (tests/rom/replays/generate.py): every press
    is judged as recorded and the final screen (counters, string name, sprites) is identical."""
    rom = ROMS["debug"]
    result = run_replay(rom, load_replay(path), load_symbols(rom.with_suffix(".noi")))
    assert result.ok, "\n".join(result.mismatches)


def test_every_string_has_a_replay():
    names = {json.loads(p.read_text())["notes"].split(":")[0] for p in REPLAYS.glob("combat_*.json")}
    assert set(STRINGS) <= names, f"missing replays for {set(STRINGS) - names}"
