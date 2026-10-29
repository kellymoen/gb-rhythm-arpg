"""Main menu and scene switching."""

import pytest

from conftest import BOOT_FRAMES, assert_golden, boot, enter_scene, press


@pytest.mark.parametrize("variant", ["cgb", "dmg"])
def test_menu_screen(variant):
    pb = boot(variant)
    pb.tick(BOOT_FRAMES, True)
    assert_golden(pb, f"menu_{variant}")
    pb.stop(save=False)


@pytest.mark.parametrize("scene", ["combat", "calibrate", "rhythmtest"])
def test_start_returns_to_menu(scene):
    pb = boot("cgb")
    enter_scene(pb, scene)
    pb.tick(30, True)
    press(pb, "start")
    pb.tick(10, True)
    assert_golden(pb, f"menu_after_{scene}")  # the cursor stays on the scene you left
    pb.stop(save=False)


def test_your_asset_rom_boots_into_every_scene():
    """Smoke test of the ROM built from your assets: no goldens, it just has to run."""
    for scene in ["combat", "calibrate", "rhythmtest"]:
        pb = boot("mine")
        enter_scene(pb, scene)
        pb.tick(120, True)
        assert pb.memory[0xFF40] & 0x80, f"{scene}: LCD is off"
        pb.stop(save=False)
