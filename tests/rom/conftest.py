"""Shared helpers for ROM tests: headless PyBoy runs, golden screenshots and symbol hooks."""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from pyboy import PyBoy

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
ROMS = {
    "cgb": REPO / "build/beatarpg.gbc",
    "dmg": REPO / "build/beatarpg-dmg.gb",
    "debug": REPO / "build/beatarpg-debug.gbc",
}


def boot(variant: str, sound: bool = False) -> PyBoy:
    rom = ROMS[variant]
    if not rom.exists():
        pytest.fail(f"{rom.relative_to(REPO)} missing; run `make test-rom` (it builds every variant)")
    return PyBoy(str(rom), window="null", cgb=variant != "dmg", sound_emulated=sound)


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
