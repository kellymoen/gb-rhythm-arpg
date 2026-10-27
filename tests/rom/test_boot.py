"""ROM smoke tests: boot each built ROM headless in PyBoy and compare a screenshot to a golden PNG.

Run via `make test-rom`. Set UPDATE_GOLDEN=1 to (re)record goldens after an intended visual change,
then review the PNGs in tests/rom/golden/ before committing.
"""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from pyboy import PyBoy

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
FRAMES = 120

ROMS = [
    ("cgb", REPO / "build" / "beatarpg.gbc", True),
    ("dmg", REPO / "build" / "beatarpg-dmg.gb", False),
]


def screenshot(rom: Path, cgb: bool) -> Image.Image:
    pyboy = PyBoy(str(rom), window="null", cgb=cgb, sound_emulated=False)
    try:
        pyboy.tick(FRAMES, render=True)
        return pyboy.screen.image.convert("RGB")
    finally:
        pyboy.stop(save=False)


@pytest.mark.parametrize("name, rom, cgb", ROMS, ids=[r[0] for r in ROMS])
def test_boot_screen_matches_golden(name, rom, cgb):
    if not rom.exists():
        pytest.fail(f"{rom.relative_to(REPO)} missing; run `make` and `make DMG=1` first")
    shot = screenshot(rom, cgb)
    golden = GOLDEN / f"boot_{name}.png"
    if os.environ.get("UPDATE_GOLDEN") == "1" or not golden.exists():
        GOLDEN.mkdir(exist_ok=True)
        shot.save(golden)
        pytest.skip(f"recorded {golden.relative_to(REPO)}; review it and re-run")
    diff = ImageChops.difference(shot, Image.open(golden).convert("RGB")).getbbox()
    if diff:
        out = REPO / "build" / f"boot_{name}_actual.png"
        shot.save(out)
        pytest.fail(f"screen differs from {golden.name} in region {diff}; actual saved to {out}")
