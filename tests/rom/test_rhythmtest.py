"""The M1 rhythm-test ROM, run headless in PyBoy (deterministic, so exact goldens are stable).

Record goldens after an intended visual change with `UPDATE_GOLDEN=1 make test-rom`, then review the
PNGs in tests/rom/golden/ before committing.
"""

import pytest

from conftest import REPO, assert_golden, boot, enter_scene, press, symbols

FRAMES_PER_PRESS = 37  # deliberately not a multiple of the 14-frame 8th note, so presses drift


@pytest.mark.parametrize("variant", ["cgb", "dmg"])
def test_idle_screen(variant):
    pb = boot(variant)
    enter_scene(pb, "rhythmtest")
    pb.tick(110, True)
    assert_golden(pb, f"rhythmtest_idle_{variant}")
    pb.stop(save=False)


def test_presses_are_graded_and_counted():
    pb = boot("cgb")
    enter_scene(pb, "rhythmtest")
    pb.tick(190, True)
    press(pb, "a")
    pb.tick(30, True)
    press(pb, "b")
    pb.tick(5, True)
    assert_golden(pb, "rhythmtest_after_presses")
    pb.stop(save=False)


def test_debug_menu_opens_with_select():
    pb = boot("debug")
    enter_scene(pb, "rhythmtest")
    pb.tick(110, True)
    press(pb, "select")
    pb.tick(10, True)  # one row per frame
    for button in ("down", "down", "left"):  # steps_per_beat 2 -> 1
        press(pb, button)
        pb.tick(2, True)  # released for a frame, so the next press is a new edge
    pb.tick(4, True)
    assert_golden(pb, "rhythmtest_debug_menu")
    pb.stop(save=False)


def test_debug_menu_reaches_every_tuning_param():
    """ADR 0004: every tuning param is tunable live in the debug menu. Walk every page (A turns it) and
    every row, nudge the param under the cursor and check that exactly its tuning_t field moved."""
    from gbtools import tuning

    params = tuning.parse_params(REPO / "data" / "tuning.toml")
    pb = boot("debug")
    base = symbols("debug")["_tuning"]
    enter_scene(pb, "rhythmtest")
    pb.tick(110, True)
    press(pb, "select")

    def tap(button):
        press(pb, button)
        pb.tick(2, True)  # released for a frame, so the next tap is a new edge

    def values():
        raw = bytes(pb.memory[base + i] for i in range(2 * len(params)))
        return [int.from_bytes(raw[2 * i:2 * i + 2], "little", signed=True) for i in range(len(params))]

    rows = 6  # DEBUGMENU_ROWS - 1
    pages = []
    for table in dict.fromkeys(p.table for p in params):
        idx = [i for i, p in enumerate(params) if p.table == table]
        pages += [idx[k:k + rows] for k in range(0, len(idx), rows)]
    seen, cursor = set(), 0
    for page in pages:
        cursor = min(cursor, len(page) - 1)
        for row, i in enumerate(page):
            for _ in range((row - cursor) % len(page)):
                tap("down")
            cursor = row
            before = values()
            p = params[i]
            nudge, back = ("left", "right") if before[i] > p.min else ("right", "left")
            tap(nudge)
            after = values()
            changed = [params[k].name for k in range(len(params)) if before[k] != after[k]]
            assert changed == [p.name], f"{nudge} on page row {row} of [{p.table}] changed {changed}, not {p.name}"
            tap(back)
            assert values() == before
            seen.add(i)
        tap("a")
    pb.stop(save=False)
    assert seen == set(range(len(params)))


def test_all_four_channels_play():
    pb = boot("cgb", sound=True)
    enter_scene(pb, "rhythmtest")
    pb.tick(190, True, True)
    nr52 = pb.memory[0xFF26]
    peak = max(abs(int(v)) for v in pb.sound.ndarray.flatten())
    pb.stop(save=False)
    assert nr52 & 0x80, "APU is off"
    assert nr52 & 0x0F == 0x0F, f"channels on = {nr52 & 0x0F:04b}, expected P1, P2, WAVE and NOISE"
    assert peak > 0, "silent output"


@pytest.mark.parametrize("variant", ["cgb", "mine"])
def test_main_loop_never_misses_a_frame(variant):
    """Feel depends on the HUD moving every frame, so the main loop must finish within a frame even on
    frames with a press, a beat change and a burst of note events."""
    pb = boot(variant)
    syms = symbols(variant)
    enter_scene(pb, "rhythmtest")
    frame = [0]
    reached = set()
    pb.hook_register(0, syms["_vsync"], lambda _: reached.add(frame[0]), None)
    for f in range(720):
        frame[0] = f
        if f % FRAMES_PER_PRESS == 0:
            pb.button("a")
        pb.tick(1, False)
    pb.stop(save=False)
    missed = [f for f in range(120, 720) if f not in reached]
    assert not missed, f"main loop overran a frame at frames {missed}"
