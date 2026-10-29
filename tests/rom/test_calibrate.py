"""Calibration scene (src/scenes/calibrate.c), battery-SRAM settings and the DEBUG timing overlay.

Taps are scripted against the ROM's own beat clock: between frames the test reads the clock, works
out the raw error (nearest beat, no latency offset) a press would get, and presses A on the frame
that gives the error it wants. So "3 frames late" is exact.

The VBlank ISR steps the clock in music_update() and then reads the joypad in input_poll(). The
music update outlasts the 10 VBlank lines, so PyBoy's frame boundary falls between the two: a press
made between ticks is judged at the clock as read between ticks. Every scripted tap checks this
against the clock seen at beat_judge() and fails loudly if the ISR timing changes.
"""

import io
import re
import statistics

import pytest
from pyboy import PyBoy

from conftest import BOOT_FRAMES, REPO, ROMS, assert_golden, enter_scene, press, symbols

TAPS = 16  # CALIB_TAPS (src/core/calib.h)
PROMPT_DELAY = 32  # frames after the last tap before A/B act (src/scenes/calibrate.c)
BEAT_TICKS = 48
SCENE_LOAD_FRAMES = 10
SRAM_SIZE = 0x2000  # one 8 KB bank (-Wm-ya1)
MAGIC = b"BARP"
SETTINGS_VERSION = 1


def boot(variant: str, ram: bytes | None = None) -> PyBoy:
    """Like conftest.boot, but with explicit cartridge RAM so no stray .ram file next to the ROM
    leaks a saved latency into these tests."""
    rom = ROMS[variant]
    if not rom.exists():
        pytest.fail(f"{rom.relative_to(REPO)} missing; run `make test-rom` (it builds every variant)")
    data = ram if ram is not None else bytes(SRAM_SIZE)
    return PyBoy(str(rom), window="null", cgb=variant != "dmg", ram_file=io.BytesIO(data))


def stop(pb: PyBoy) -> bytes:
    """Stop the emulator and return its cartridge RAM (what the battery would keep)."""
    out = io.BytesIO()
    pb.stop(save=True, ram_file=out)
    return out.getvalue()


def tuning_offsets(variant: str) -> dict[str, int]:
    """Byte offset of each tuning_t field, from the generated header (every field is an int16)."""
    header = (ROMS[variant].parent / "gen" / "tuning.h").read_text()
    body = header[header.index("typedef struct {") : header.index("} tuning_t;")]
    names = re.findall(r"int16_t (\w+);", body)
    return {name: 2 * i for i, name in enumerate(names)}


class Rom:
    """A booted ROM plus the symbols and RAM fields the tests read."""

    def __init__(self, variant: str, ram: bytes | None = None):
        self.variant = variant
        self.pb = boot(variant, ram)
        self.syms = symbols(variant)
        self.fields = tuning_offsets(variant)
        self.judged = []  # the clock at every beat_judge() call
        a = self.syms["_beat_judge"]
        self.pb.hook_register(a >> 16, a & 0xFFFF, lambda _: self.judged.append(self.clock()), None)

    def tuning(self, field: str) -> int:
        addr = self.syms["_tuning"] + self.fields[field]
        v = self.pb.memory[addr] | self.pb.memory[addr + 1] << 8
        return v - 0x10000 if v & 0x8000 else v

    def clock(self) -> tuple[int, int, int, int]:
        m, a = self.pb.memory, self.syms["_music_clock"]
        return m[a] | m[a + 1] << 8, m[a + 2], m[a + 3], m[a + 4] | m[a + 5] << 8

    def tap(self, errors: list[int], max_frames: int = 3000) -> None:
        """Press A once per beat so each press is judged `errors[i]` frames from its beat."""
        last_slot, i = 0, 0  # never tap the beat the song starts on
        start = len(self.judged)
        for _ in range(max_frames):
            if i == len(errors):
                break
            frames, slot = judge(*self.clock())
            if frames == errors[i] and slot > last_slot:
                self.pb.button("a")
                last_slot, i = slot, i + 1
            self.pb.tick(1, False)
        else:
            pytest.fail(f"only {i} of {len(errors)} taps landed in {max_frames} frames")
        self.pb.tick(1, False)
        landed = [judge(*c)[0] for c in self.judged[start:]]
        assert landed == errors, "tap script missed its targets: did the VBlank ISR timing change?"


def judge(beat: int, tick: int, frac: int, rate: int) -> tuple[int | None, int]:
    """beat_judge (src/core/beat.c) with one slot per beat and no latency offset: (frames, slot).
    Frames is None until the song is playing."""
    if rate == 0:
        return None, 0
    slot_len = BEAT_TICKS << 8
    pos = (tick << 8) + frac
    late = pos <= slot_len // 2
    dist = (pos if late else slot_len - pos) + (rate >> 1)
    frames = dist // rate
    return (frames if late else -frames), (beat if late else beat + 1)


def expected_median(errors: list[int]) -> int:
    m = statistics.median(errors)
    return int(m + 0.5) if m >= 0 else -int(-m + 0.5)  # halves round away from zero


def record(latency: int) -> bytes:
    """The settings record the ROM writes at 0xA000 (src/gb/settings.h)."""
    head = MAGIC + bytes([SETTINGS_VERSION, latency & 0xFF])
    return head + bytes([~sum(head) & 0xFF])


def finish_taps(rom: Rom, errors: list[int]) -> None:
    rom.tap(errors)
    rom.pb.tick(PROMPT_DELAY + 8, True)


@pytest.mark.parametrize("variant", ["cgb", "dmg"])
def test_start_screen(variant):
    rom = Rom(variant)
    enter_scene(rom.pb, "calibrate")
    rom.pb.tick(30, True)
    assert_golden(rom.pb, f"calibrate_start_{variant}")
    stop(rom.pb)


def test_late_taps_become_the_saved_offset():
    rom = Rom("cgb")
    enter_scene(rom.pb, "calibrate")
    rom.pb.tick(2, True)
    # Grading is raw while calibrating: one slot per beat, no latency offset, no musical hits.
    assert (rom.tuning("timing_steps_per_beat"), rom.tuning("timing_latency_offset")) == (1, 0)
    assert rom.tuning("feedback_musical_hits") == 0

    rom.tap([3] * TAPS)
    press(rom.pb, "a")  # a stray 17th tap right after the last one must not accept
    rom.pb.tick(PROMPT_DELAY + 8, True)
    assert_golden(rom.pb, "calibrate_result")
    assert rom.tuning("timing_latency_offset") == 0, "accepted before the prompt appeared"

    press(rom.pb, "a")  # Accept
    rom.pb.tick(10, True)
    assert_golden(rom.pb, "calibrate_saved")
    press(rom.pb, "start")
    rom.pb.tick(10, True)
    assert rom.tuning("timing_latency_offset") == 3
    assert rom.tuning("timing_steps_per_beat") == 2, "steps_per_beat not restored"
    assert rom.tuning("feedback_musical_hits") == 1, "musical hits not restored"
    assert stop(rom.pb)[: len(record(3))] == record(3)


def test_median_ignores_wild_taps_and_overlay_plots_them():
    """DEBUG ROM: the press log shows each tap was judged raw at exactly the scripted error, the
    median ignores the outliers, and the timing overlay is drawn (golden)."""
    errors = [3, -2, 4, 5, -12, 2, 3, 12, 4, -1, 2, 6, 3, -4, 5, 2]
    rom = Rom("debug")
    enter_scene(rom.pb, "calibrate")
    head0 = rom.pb.memory[rom.syms["_press_log_head"]]
    rom.tap(errors)
    rom.pb.tick(PROMPT_DELAY + 8, True)
    assert_golden(rom.pb, "calibrate_debug_overlay")

    log, head = rom.syms["_press_log"], rom.pb.memory[rom.syms["_press_log_head"]]
    assert (head - head0) & 0xFF == TAPS
    judged = []
    for k in range(head - TAPS, head):  # 16-entry ring, 4 bytes per entry: frame, buttons, grade, frames
        v = rom.pb.memory[log + 4 * (k & 15) + 3]
        judged.append(v - 0x100 if v & 0x80 else v)
    assert judged == errors

    press(rom.pb, "a")
    rom.pb.tick(10, True)
    press(rom.pb, "start")
    rom.pb.tick(10, True)
    assert expected_median(errors) == 3
    assert rom.tuning("timing_latency_offset") == 3
    stop(rom.pb)


def test_select_hides_the_overlay():
    rom = Rom("debug")
    enter_scene(rom.pb, "calibrate")
    rom.pb.tick(10, True)
    oam = 0xFE00 + 4 * 12  # overlay OAM 12-15 (src/gb/overlay.c)
    assert rom.pb.memory[oam] != 0, "overlay not shown"
    press(rom.pb, "select")
    rom.pb.tick(4, True)
    assert all(rom.pb.memory[oam + 4 * i] == 0 for i in range(4)), "overlay still shown"
    stop(rom.pb)


def test_retry_starts_over():
    rom = Rom("cgb")
    enter_scene(rom.pb, "calibrate")
    finish_taps(rom, [6] * TAPS)
    press(rom.pb, "b")  # Retry
    rom.pb.tick(20, True)
    assert_golden(rom.pb, "calibrate_retry")
    finish_taps(rom, [-2] * TAPS)
    press(rom.pb, "a")
    rom.pb.tick(10, True)
    press(rom.pb, "start")
    rom.pb.tick(10, True)
    assert rom.tuning("timing_latency_offset") == -2
    assert stop(rom.pb)[:7] == record(-2)


def test_back_without_accepting_changes_nothing():
    rom = Rom("cgb")
    enter_scene(rom.pb, "calibrate")
    finish_taps(rom, [5] * TAPS)
    press(rom.pb, "start")
    rom.pb.tick(10, True)
    assert rom.tuning("timing_latency_offset") == 0
    assert rom.tuning("timing_steps_per_beat") == 2
    assert rom.tuning("feedback_musical_hits") == 1
    assert stop(rom.pb)[:7] == bytes(7), "SRAM written without Accept"


def booted_latency(ram: bytes) -> int | None:
    """Boot with this cartridge RAM and return the latency offset in effect at the menu, or None
    if main() never called settings_load() (it is wired in by integration, see the report)."""
    rom = Rom("cgb", ram)
    called = []
    sym = rom.syms["_settings_load"]
    rom.pb.hook_register(sym >> 16, sym & 0xFFFF, lambda _: called.append(1), None)
    rom.pb.tick(BOOT_FRAMES, False)
    latency = rom.tuning("timing_latency_offset")
    stop(rom.pb)
    return latency if called else None


def test_saved_offset_survives_a_reset():
    rom = Rom("cgb")
    enter_scene(rom.pb, "calibrate")
    finish_taps(rom, [-4] * TAPS)
    press(rom.pb, "a")
    rom.pb.tick(10, True)
    ram = stop(rom.pb)
    assert ram[:7] == record(-4)

    latency = booted_latency(ram)
    if latency is None:
        pytest.skip("main() does not call settings_load() yet")
    assert latency == -4

    # Anything but a valid record leaves the tuning default (0).
    blank = bytearray(SRAM_SIZE)
    for bad in (
        record(-4)[:6] + bytes([record(-4)[6] ^ 1]),  # checksum
        b"BARQ" + record(-4)[4:],  # magic
        MAGIC + bytes([SETTINGS_VERSION + 1]) + record(-4)[5:],  # version
        record(16),  # out of range
    ):
        blank[:7] = bad
        assert booted_latency(bytes(blank)) == 0, f"accepted bad record {bad.hex()}"


@pytest.mark.parametrize("variant", ["cgb", "debug", "mine"])
def test_main_loop_never_misses_a_frame(variant):
    """Taps, text jobs, the result and (DEBUG) the overlay redraw all fit in a frame."""
    rom = Rom(variant)
    enter_scene(rom.pb, "calibrate")
    frame = [0]
    reached = set()
    rom.pb.hook_register(0, rom.syms["_vsync"], lambda _: reached.add(frame[0]), None)
    errors = [2, -3, 5, 0, 7, -6, 1, 4, -1, 3, 2, -2, 6, 0, 1, 3]
    last_slot, i = 0, 0
    for f in range(900):
        frame[0] = f
        if i < TAPS:
            frames, slot = judge(*rom.clock())
            if frames == errors[i] and slot > last_slot:
                rom.pb.button("a")
                last_slot, i = slot, i + 1
        elif f % 60 == 0:
            rom.pb.button("b" if f % 120 else "a")  # retry / accept cycles redraw everything
        rom.pb.tick(1, False)
    stop(rom.pb)
    assert i == TAPS
    # The first frames load the scene and start the song (its first VBlank runs every channel's
    # start-up events, like the rhythm test's, whose frame test also starts late).
    missed = [f for f in range(SCENE_LOAD_FRAMES, 900) if f not in reached]
    assert not missed, f"main loop overran a frame at frames {missed}"
