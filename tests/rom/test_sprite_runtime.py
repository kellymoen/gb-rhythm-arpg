"""The sprite runtime in the combat scene's sprite viewer (src/scenes/combatflat.c), headless in PyBoy.

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
ACTIONS_TO_LIGHT1 = 4  # A steps idle -> walk -> dodge -> hurt -> light1

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
    keys = DIRECTIONS[direction]
    for k in keys:
        pb.button_press(k)
    pb.tick(4, True)
    for k in keys:
        pb.button_release(k)
    pb.tick(12, True)


@pytest.mark.parametrize("direction", list(DIRECTIONS))
def test_facings(direction):
    """The player in every drawn facing and one mirrored one, the dummy idling beside them."""
    pb = viewer()
    face(pb, direction)
    assert_golden(pb, f"sprite_facing_{direction}")
    pb.stop(save=False)


def test_idle_dmg():
    pb = viewer("dmg")
    assert_golden(pb, "sprite_idle_dmg")
    pb.stop(save=False)


def attack(pb) -> None:
    """From idle, step the actions forward to LIGHT1 (each A press starts the next one)."""
    for _ in range(ACTIONS_TO_LIGHT1):
        press(pb, "a")
        pb.tick(3, True)


def test_attack_hit_frame():
    """LIGHT1 on its hit frame (the slash), the dummy still idle."""
    pb = viewer()
    attack(pb)
    pb.tick(6, True)
    assert_golden(pb, "sprite_attack_light1")
    pb.stop(save=False)


def test_dummy_flinches():
    """A few frames after the hit frame the dummy plays its hurt anim (frozen by hitstop first)."""
    pb = viewer()
    attack(pb)
    pb.tick(9, True)
    assert_golden(pb, "sprite_dummy_hurt")
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
    its tiles: the double buffer never shows a half-copied slot and the HBlank copy loses no bytes."""
    frames = {"player": tile_arrays("player"), "dummy": tile_arrays("dummy")}
    pb = viewer()
    checked = 0
    for f in range(480):
        if f % 7 == 0:
            pb.button("a" if f % 14 else "b")
        if f % 50 == 25:
            pb.button_press("left")
        if f % 50 == 30:
            pb.button_release("left")
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


@pytest.mark.parametrize("variant", ["cgb", "dmg", "mine"])
def test_main_loop_never_misses_a_frame_while_streaming(variant):
    """Attacks spammed on both buttons, turning as we go: anims change frame on and off the beat and
    tiles stream every few frames, and the main loop still finishes inside every frame. Runs 700
    frames: the rhythm-test song loops at ~900, where the sound driver's restart takes ~110 lines of
    VBlank ISR and drops a frame whatever the scene does (see the M2 sprite-runtime report)."""
    pb = boot(variant)
    syms = symbols(variant)
    enter_scene(pb, "combat")
    pb.tick(SETTLE, True)
    frame = [0]
    reached = set()
    streamed = []
    pb.hook_register(0, syms["_vsync"], lambda _: reached.add(frame[0]), None)
    for f in range(700):
        frame[0] = f
        if f % 5 == 0:
            pb.button("a" if f % 3 else "b")
        if f % 40 == 20:
            pb.button_press("right")
        if f % 40 == 24:
            pb.button_release("right")
        pb.tick(1, False)
        streamed.append(pb.memory[syms["_vram_stream_last_bytes"]])
    pb.stop(save=False)
    missed = [f for f in range(2, 700) if f not in reached]
    assert not missed, f"main loop overran a frame at frames {missed}"
    assert sum(streamed) > 192 * 20, "expected the attacks to stream tiles"
