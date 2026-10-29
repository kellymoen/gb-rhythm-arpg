"""Main menu and scene switching."""

import re

import pytest

from conftest import BOOT_FRAMES, ROMS, assert_golden, boot, enter_scene, press, symbols


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


def test_menu_sounds():
    """Moving the cursor plays SFX_MENU_MOVE; picking a scene plays SFX_MENU_SELECT."""
    header = (ROMS["cgb"].parent / "gen" / "sfx.h").read_text()
    ids = {m[1]: int(m[2]) for m in re.finditer(r"#define SFX_(\w+) (\d+)", header)}
    pb = boot("cgb")
    syms = symbols("cgb")
    played = []
    a = syms["_sfx_play"]
    pb.hook_register(a >> 16, a & 0xFFFF, lambda _: played.append(pb.register_file.A), None)
    pb.tick(BOOT_FRAMES, True)
    press(pb, "down")
    pb.tick(2, True)
    press(pb, "up")
    pb.tick(2, True)
    assert played == [ids["MENU_MOVE"]] * 2
    press(pb, "a")
    pb.tick(2, True)
    assert played[2] == ids["MENU_SELECT"]
    pb.stop(save=False)
