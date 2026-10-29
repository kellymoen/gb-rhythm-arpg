"""Convert a 4-shade PNG into Game Boy 2bpp tile data: build/gen/<symbol>.{c,h}.

Colour mapping: an indexed PNG (Aseprite's Indexed mode; preferred) uses its palette indices directly
(0 = lightest / sprite transparency, 3 = darkest). Any other PNG maps each colour to the nearest of
four evenly spaced brightness levels; fully transparent pixels are 0.
Tiles are read left-to-right, top-to-bottom. With --sprite8x16 each 8x16 block is emitted as its top
then bottom tile, matching 8x16 sprite mode. With --banked the data goes to a switchable ROM bank
(`#pragma bank 255`, BANKREF(<symbol>)), for sheets that are copied with a banked VRAM copy rather than
read from bank 0.
"""

import argparse
import sys
from pathlib import Path

from PIL import Image

from gbtools.errors import ConvertError


def shades(img: Image.Image, path: Path) -> list[list[int]]:
    w, h = img.size
    if img.mode == "P":
        px = img.load()
        grid = [[px[x, y] for x in range(w)] for y in range(h)]
        bad = sorted({v for row in grid for v in row if v > 3})
        if bad:
            raise ConvertError(path, f"uses palette indices {bad}; only indices 0-3 (4 shades) are allowed, so "
                                     f"repaint those pixels with the first four palette colours")
        return grid
    rgba = img.convert("RGBA")
    px = rgba.load()
    colours = {px[x, y][:3] for y in range(h) for x in range(w) if px[x, y][3] != 0}
    if len(colours) > 4:
        raise ConvertError(path, f"has {len(colours)} colours; Game Boy tiles allow 4 shades, so reduce it to 4 "
                                 f"colours (or save it as an indexed PNG using palette indices 0-3)")
    index = {c: round((255 - (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])) / 85) for c in colours}
    for shade in range(4):
        same = [c for c, s in index.items() if s == shade]
        if len(same) > 1:
            raise ConvertError(path, f"colours {same} are too close in brightness to tell apart as "
                                     f"shades; save it as an indexed PNG to choose shades exactly")
    return [[0 if px[x, y][3] == 0 else index[px[x, y][:3]] for x in range(w)] for y in range(h)]


def tile_bytes(grid, tx: int, ty: int) -> bytes:
    out = bytearray()
    for y in range(ty, ty + 8):
        lo = hi = 0
        for x in range(tx, tx + 8):
            v = grid[y][x]
            lo = (lo << 1) | (v & 1)
            hi = (hi << 1) | (v >> 1)
        out += bytes([lo, hi])
    return bytes(out)


def convert(path: Path, sprite8x16: bool) -> list[bytes]:
    try:
        img = Image.open(path)
    except OSError as e:
        raise ConvertError(path, f"cannot read PNG: {e}; re-save it as a PNG") from e
    w, h = img.size
    step_h = 16 if sprite8x16 else 8
    if w % 8 or h % step_h:
        raise ConvertError(path, f"is {w}x{h}; width must be a multiple of 8 and height of {step_h}, so resize "
                                 f"the canvas")
    grid = shades(img, path)
    tiles = []
    for ty in range(0, h, step_h):
        for tx in range(0, w, 8):
            tiles.append(tile_bytes(grid, tx, ty))
            if sprite8x16:
                tiles.append(tile_bytes(grid, tx, ty + 8))
    return tiles


def render(symbol: str, tiles: list[bytes], source: str, banked: bool = False) -> tuple[str, str]:
    banner = f"/* Generated from {source} by tools/gbtools/tiles.py. Do not edit. */\n"
    guard = f"GEN_{symbol.upper()}_H"
    includes = "#include <stdint.h>\n" + ("#include <gbdk/platform.h>\n" if banked else "")
    bankref = f"BANKREF_EXTERN({symbol})\n" if banked else ""
    header = (banner + f"#ifndef {guard}\n#define {guard}\n\n{includes}\n"
              + f"#define {symbol.upper()}_TILE_COUNT {len(tiles)}\n"
              + bankref + f"extern const uint8_t {symbol}_tiles[];\n\n#endif\n")
    rows = "".join("    " + ", ".join(f"0x{b:02X}" for b in t) + ",\n" for t in tiles)
    pragma = "#pragma bank 255\n\n" if banked else ""
    ref = f"BANKREF({symbol})\n\n" if banked else ""
    source_c = (banner + pragma + f'#include "{symbol}.h"\n\n' + ref
                + f"const uint8_t {symbol}_tiles[] = {{\n{rows}}};\n")
    return header, source_c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbtools.tiles")
    ap.add_argument("png", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("symbol")
    ap.add_argument("--sprite8x16", action="store_true")
    ap.add_argument("--banked", action="store_true", help="put the tiles in a switchable ROM bank")
    args = ap.parse_args(argv)
    try:
        tiles = convert(args.png, args.sprite8x16)
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    header, source_c = render(args.symbol, tiles, args.png.as_posix(), args.banked)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{args.symbol}.h").write_text(header)
    (args.out_dir / f"{args.symbol}.c").write_text(source_c)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
