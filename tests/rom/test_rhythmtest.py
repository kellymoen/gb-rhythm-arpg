"""The M1 rhythm-test ROM, run headless in PyBoy (deterministic, so exact goldens are stable).

Record goldens after an intended visual change with `UPDATE_GOLDEN=1 make test-rom`, then review the
PNGs in tests/rom/golden/ before committing.
"""

import pytest

from conftest import assert_golden, boot, enter_scene, press, symbols

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
    pb.tick(4, True)
    press(pb, "right")  # latency +1
    pb.tick(4, True)
    assert_golden(pb, "rhythmtest_debug_menu")
    pb.stop(save=False)


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
