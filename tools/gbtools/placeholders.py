"""Generate placeholder assets that follow the asset contract (ADR 0006), for the author to replace.

    python -m gbtools.placeholders [--force] {song,font,hud,all}

Every file is written as `<name>_genplaceholder.<ext>` (ADR 0007); the author replaces it by saving
`<name>.<ext>` beside it. Never run by the build: it refuses to overwrite an existing placeholder
unless --force is given, and never writes one the author's file has already replaced.
"""

import argparse
import sys
from pathlib import Path

import mido
from PIL import Image

from gbtools.assets import PLACEHOLDER

REPO = Path(__file__).resolve().parents[2]
SHADES = [(232, 240, 216), (152, 184, 120), (72, 104, 72), (16, 32, 32)]

# Glyph order is part of the contract with src/gb/text.c.
FONT_CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-.:/!?%><"
FONT_5X7 = {
    " ": ["     "] * 7,
    "0": [" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "],
    "1": ["  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"],
    "3": ["#####", "   # ", "  #  ", "   # ", "    #", "#   #", " ### "],
    "4": ["   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "],
    "5": ["#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "],
    "6": ["  ## ", " #   ", "#    ", "#### ", "#   #", "#   #", " ### "],
    "7": ["#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "],
    "8": [" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "],
    "9": [" ### ", "#   #", "#   #", " ####", "    #", "   # ", " ##  "],
    "A": [" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "B": ["#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "],
    "C": [" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "],
    "D": ["#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"],
    "F": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "],
    "G": [" ### ", "#   #", "#    ", "# ###", "#   #", "#   #", " ####"],
    "H": ["#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "I": [" ### ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "],
    "J": ["  ###", "   # ", "   # ", "   # ", "   # ", "#  # ", " ##  "],
    "K": ["#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"],
    "N": ["#   #", "#   #", "##  #", "# # #", "#  ##", "#   #", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "P": ["#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"],
    "R": ["#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"],
    "S": [" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "V": ["#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "#   #", "# # #", "# # #", "# # #", " # # "],
    "X": ["#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"],
    "Y": ["#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "],
    "Z": ["#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"],
    "+": ["     ", "  #  ", "  #  ", "#####", "  #  ", "  #  ", "     "],
    "-": ["     ", "     ", "     ", "#####", "     ", "     ", "     "],
    ".": ["     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "],
    ":": ["     ", " ##  ", " ##  ", "     ", " ##  ", " ##  ", "     "],
    "/": ["     ", "    #", "   # ", "  #  ", " #   ", "#    ", "     "],
    "!": ["  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "],
    "?": [" ### ", "#   #", "    #", "   # ", "  #  ", "     ", "  #  "],
    "%": ["##   ", "##  #", "   # ", "  #  ", " #   ", "#  ##", "   ##"],
    ">": [" #   ", "  #  ", "   # ", "    #", "   # ", "  #  ", " #   "],
    "<": ["   # ", "  #  ", " #   ", "#    ", " #   ", "  #  ", "   # "],
}


def _indexed(w: int, h: int) -> Image.Image:
    img = Image.new("P", (w, h), 0)
    img.putpalette([c for rgb in SHADES for c in rgb])
    return img


def _write(name: str, force: bool, save) -> None:
    """`name` is the asset path without the suffix, e.g. "assets/ui/font.png"."""
    mine = REPO / name
    path = mine.with_name(mine.stem + PLACEHOLDER + mine.suffix)
    if mine.exists():
        print(f"skip {path.relative_to(REPO)} (replaced by your {mine.relative_to(REPO)})")
        return
    if path.exists() and not force:
        print(f"skip {path.relative_to(REPO)} (exists; use --force to overwrite)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path)
    print(f"wrote {path.relative_to(REPO)}")


def font(force: bool) -> None:
    """16 glyphs per row, 8x8 cells, ink = shade 3 on shade 0."""
    rows = -(-len(FONT_CHARS) // 16)
    img = _indexed(128, rows * 8)
    for i, ch in enumerate(FONT_CHARS):
        ox, oy = (i % 16) * 8 + 1, (i // 16) * 8
        for y, line in enumerate(FONT_5X7[ch]):
            for x, c in enumerate(line):
                if c == "#":
                    img.putpixel((ox + x, oy + y), 3)
    _write("assets/ui/font.png", force, img.save)


def hud(force: bool) -> None:
    """hud_bar.png: window tiles [bar, hit marker]. hud_sprites.png: 8x16 sprites [pip, downbeat pip]."""
    bar = _indexed(16, 8)
    for x in range(16):
        bar.putpixel((x, 0), 2)
        bar.putpixel((x, 7), 2)
    for x in range(8, 16):
        for y in range(1, 7):
            bar.putpixel((x, y), 1)
    for y in range(0, 8):
        bar.putpixel((11, y), 3)
        bar.putpixel((12, y), 3)
    _write("assets/ui/hud_bar.png", force, bar.save)

    spr = _indexed(16, 16)
    for (cx, r) in ((3, 1), (11, 3)):  # pip centre x and radius, both centred on row 3
        for y in range(8):
            for x in range(cx - 3, cx + 5):
                d = abs(x - cx) + abs(y - 3)
                if d <= r:
                    spr.putpixel((x, y), 3 if d < r else 2)
    _write("assets/ui/hud_sprites.png", force, spr.save)


def song(force: bool) -> None:
    """rhythmtest.mid: 128 BPM, 4/4, 8 bars, Am-F-C-G, every track type the converter understands."""
    ppq, bar = 480, 480 * 4
    eighth, sixteenth = ppq // 2, ppq // 4
    chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]  # Am F C G (root, 3rd, 5th)
    mid = mido.MidiFile(type=1, ticks_per_beat=ppq)

    def track(name: str, program: int | None, notes: list[tuple[int, int, int, int]]) -> None:
        t = mido.MidiTrack()
        t.append(mido.MetaMessage("track_name", name=name, time=0))
        msgs = []
        if program is not None:
            msgs.append((0, 0, mido.Message("program_change", program=program)))
        for start, length, note, vel in notes:
            msgs.append((start, 2, mido.Message("note_on", note=note, velocity=vel)))
            msgs.append((start + length, 1, mido.Message("note_off", note=note, velocity=0)))
        now = 0
        for at, _, msg in sorted(msgs, key=lambda m: (m[0], m[1])):
            t.append(msg.copy(time=at - now))
            now = at
        mid.tracks.append(t)

    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(128), time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(conductor)

    lead, stabs, bass, drums = [], [], [], []
    for b in range(8):
        root, third, fifth = chords[b // 2]
        start = b * bar
        arp = [root, third, fifth, root + 12, fifth + 12, root + 12, fifth, third]
        for i, n in enumerate(arp):
            lead.append((start + i * eighth, eighth - 30, n + 12, 110 if i % 2 == 0 else 80))
        for beat in range(4):
            stabs.append((start + beat * ppq + eighth, sixteenth, third + 12, 70))
            drums.append((start + beat * ppq, sixteenth, 36 if beat % 2 == 0 else 38, 120))
            hat = 46 if (b % 2 == 1 and beat == 3) else 42
            drums.append((start + beat * ppq + eighth, sixteenth, hat, 60))
        for beat in (0, 2):
            bass.append((start + beat * ppq, ppq * 2 - 40, root - 12, 120))

    track("P1", 0, lead)
    track("P2", 1, stabs)
    track("WAVE", 0, bass)
    track("NOISE", None, drums)
    track("HITS", 2, [(i * eighth, eighth, n, 100) for i, n in enumerate([69, 72, 74, 76, 79, 81])])
    _write("assets/music/rhythmtest.mid", force, lambda p: mid.save(p))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbtools.placeholders")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("what", choices=["song", "font", "hud", "all"])
    args = ap.parse_args(argv)
    for name, fn in (("song", song), ("font", font), ("hud", hud)):
        if args.what in (name, "all"):
            fn(args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
