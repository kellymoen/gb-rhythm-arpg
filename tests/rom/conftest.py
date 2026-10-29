"""Shared helpers for ROM tests: headless PyBoy runs, golden screenshots and symbol hooks."""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from pyboy import PyBoy

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
# Goldens use the placeholders-only ROMs (build/ph/, ADR 0007) so replacing an asset with your own
# never changes them. "mine" is the ROM built from your assets: smoke tests only.
ROMS = {
    "cgb": REPO / "build/ph/beatarpg.gbc",
    "dmg": REPO / "build/ph/beatarpg-dmg.gb",
    "debug": REPO / "build/ph/beatarpg-debug.gbc",
    "mine": REPO / "build/beatarpg.gbc",
}
BOOT_FRAMES = 120  # PyBoy's own boot animation runs for the first ~65 frames

# Main-menu rows (src/scenes/menu.c), in order.
MENU = ["combat", "calibrate", "rhythmtest"]


def boot(variant: str, sound: bool = False) -> PyBoy:
    rom = ROMS[variant]
    if not rom.exists():
        pytest.fail(f"{rom.relative_to(REPO)} missing; run `make test-rom` (it builds every variant)")
    return PyBoy(str(rom), window="null", cgb=variant not in ("dmg",), sound_emulated=sound)


def symbols(variant: str) -> dict[str, int]:
    out = {}
    for line in ROMS[variant].with_suffix(".noi").read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "DEF":
            out[parts[1]] = int(parts[2], 16)
    return out


def press(pb: PyBoy, button: str) -> None:
    pb.button(button)
    pb.tick(1, True)


def enter_scene(pb: PyBoy, scene: str) -> None:
    """From a fresh boot: wait for the main menu, pick `scene`, and let it load."""
    pb.tick(BOOT_FRAMES, True)
    for _ in range(MENU.index(scene)):
        press(pb, "down")
        pb.tick(2, True)
    press(pb, "a")
    pb.tick(2, True)


def assert_golden(pb: PyBoy, name: str) -> None:
    """Compare the current screen to tests/rom/golden/<name>.png. UPDATE_GOLDEN=1 re-records."""
    shot = pb.screen.image.convert("RGB")
    golden = GOLDEN / f"{name}.png"
    if os.environ.get("UPDATE_GOLDEN") == "1" or not golden.exists():
        GOLDEN.mkdir(exist_ok=True)
        shot.save(golden)
        pytest.skip(f"recorded {golden.relative_to(REPO)}; review it and re-run")
    diff = ImageChops.difference(shot, Image.open(golden).convert("RGB")).getbbox()
    if diff:
        out = REPO / "build" / f"{name}_actual.png"
        shot.save(out)
        pytest.fail(f"screen differs from {golden.name} in region {diff}; actual saved to {out}")
