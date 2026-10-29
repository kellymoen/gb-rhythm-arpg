"""The sprite runtime in the combat scene (src/scenes/combatflat.c), headless in PyBoy. The M2 sprite
viewer this file first tested became the combat scene: the D-pad now walks (and turns) the player,
A/B attack (tests/rom/test_combat.py covers combat itself).

PyBoy blocks VRAM writes during mode 3 (with sprite-dependent mode-3 length), so a tile stream that
wrote outside HBlank/VBlank would lose bytes and fail test_shown_slots_hold_whole_frames.

Record goldens after an intended visual change with `UPDATE_GOLDEN=1 make test-rom`, then review them.
"""

import re

import pytest

from conftest import REPO, assert_golden, boot, enter_scene, press, symbols

SETTLE = 40  # frames for the scene to load and the first frames to stream
TILE_PLAYER, PLAYER_SLOT = 0x90, 12  # src/gb/video.h; slots of BUDGET_FRAME_TILES
TILE_DUMMY, DUMMY_SLOT = 0xA8, 8  # 16x32 enemy budget
OAM_WORLD, OAM_WORLD_COUNT = 16, 24

DIRECTIONS = {
    "s": ["down"],
    "se": ["down", "right"],
    "e": ["right"],
    "ne": ["up", "right"],
    "n": ["up"],
    "w": ["left"],  # mirrored: E drawn flipped
}


def viewer(variant: str = "cgb"):
    pb = boot(variant)
    enter_scene(pb, "combat")
    pb.tick(SETTLE, True)
    return pb


def face(pb, direction: str) -> None:
    """Walk 4 frames in `direction` (turning there), then stand."""
    keys = DIRECTIONS[direction]
    for k in keys:
        pb.button_press(k)
    pb.tick(4, True)
    for k in keys:
        pb.button_release(k)
    pb.tick(12, True)


@pytest.mark.parametrize("direction", list(DIRECTIONS))
def test_facings(direction):
    """The player in every drawn facing and one mirrored one (after a 4-frame step), the dummy idling."""
    pb = viewer()
    face(pb, direction)
    assert_golden(pb, f"sprite_facing_{direction}")
    pb.stop(save=False)


def test_idle_dmg():
    pb = viewer("dmg")
    assert_golden(pb, "sprite_idle_dmg")
    pb.stop(save=False)


def tile_arrays(name: str) -> list[bytes]:
    """Every frame's tile data of sprite `name`, from the converter's output for the test ROMs."""
    out = []
    for path in sorted((REPO / "build/ph/gen").glob(f"sprite*_{name}*.c")):
        for body in re.findall(r"static const uint8_t t\d+\[\] = \{(.*?)\};", path.read_text(), re.S):
            out.append(bytes(int(v, 16) for v in re.findall(r"0x[0-9A-Fa-f]{2}", body)))
    assert out, f"no tile data for {name} in build/ph/gen"
    return out


def shown_slot(pb, first: int, slot_tiles: int) -> int | None:
    """Which of a character's two slots the hardware OAM draws from (None: not drawn)."""
    for i in range(OAM_WORLD, OAM_WORLD + OAM_WORLD_COUNT):
        y, tile = pb.memory[0xFE00 + 4 * i], pb.memory[0xFE00 + 4 * i + 2]
        if y and first <= tile < first + 2 * slot_tiles:
            return (tile - first) // slot_tiles
    return None


def test_shown_slots_hold_whole_frames():
    """At every frame boundary, the slot each character's OAM points at holds one complete frame of
    its tiles: the double buffer never shows a half-copied slot, the HBlank copy loses no bytes and
    the VBlank copy finishes a tile the HBlank copy left half done (it once ran away there). Attacks,
    walking into the dummy and its flinches keep both characters streaming."""
    frames = {"player": tile_arrays("player"), "dummy": tile_arrays("dummy")}
    pb = viewer()
    pb.button_press("up")
    pb.tick(8, True)
    pb.button_release("up")
    pb.button_press("right")
    pb.tick(40, True)
    pb.button_release("right")
    checked = 0
    for f in range(480):
        if f % 7 == 0:
            pb.button("a" if f % 14 else "b")
        if f % 50 == 25:
            pb.button_press("left")
        if f % 50 == 30:
            pb.button_release("left")
        if f % 50 == 35:
            pb.button_press("right")
        if f % 50 == 41:
            pb.button_release("right")
        pb.tick(1, False)
        for name, first, slot_tiles in (("player", TILE_PLAYER, PLAYER_SLOT), ("dummy", TILE_DUMMY, DUMMY_SLOT)):
            slot = shown_slot(pb, first, slot_tiles)
            assert slot is not None, f"frame {f}: {name} is not drawn"
            base = 0x8000 + 16 * (first + slot * slot_tiles)
            vram = bytes(pb.memory[base : base + 16 * slot_tiles])
            assert any(vram[: len(t)] == t for t in frames[name]), (
                f"frame {f}: {name} slot {slot} at {base:#06x} holds no complete frame"
            )
            checked += 1
    pb.stop(save=False)
    assert checked == 2 * 480
