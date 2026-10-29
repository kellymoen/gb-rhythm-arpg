"""Convert an exported Aseprite sprite sheet (PNG + JSON) into banked C data (ADR 0006).

    python -m gbtools.sprites <sheet.png> <sheet.json> <out_dir> [--budgets budgets.h] [--beat beat.h]

The Makefile passes the files that tools/gbtools/export.py wrote to exports/sprites/. Both
`player_genplaceholder.png` and `player.png` become the character `player` (ADR 0007). Output layout:
src/gb/spritedata.h; author guide: docs/sprites.md.

Outputs in <out_dir> (header first, so make can treat it as the primary target):
  sprite_<name>.h            action enum SPRITE_<NAME>_<ACTION>, `sprite_<name>`, bank accessors
  sprite_<name>.c            index (sprite_t, anim table, per-anim bank table) + the first anims
  spritebank_<name>_<k>.c    k = 1..BANK_FILES-1: more anims when they do not fit one 16 KB ROM bank.
                             Always written (a stub when unused) so the Makefile can list them.

Frames are sliced into 8x16 OBJ parts on the canvas grid; parts that are fully transparent are dropped.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from gbtools.assets import asset_name
from gbtools.errors import ConvertError
from gbtools.tiles import shades, tile_bytes

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BUDGETS = REPO / "src/core/budgets.h"
DEFAULT_BEAT = REPO / "src/core/beat.h"

FACINGS = ["s", "se", "e", "ne", "n"]  # drawn facings; index = FACING_* in spritedata.h
MIRRORED = {"sw": "se", "w": "e", "nw": "ne"}
BANK_FILES = 4  # files per sprite, each in its own ROM bank when it does not fit with the others
BANK_CAP = 15000  # bytes of estimated data per file; a ROM bank is 16384
ANIM_NO_HIT = "ANIM_NO_HIT"

TAG_RE = re.compile(r"^([a-z][a-z0-9]*)(?:_([a-z]+))?$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Actions the runtime looks up per sprite (enum order). `optional` ones may be absent entirely; their
# anims are NULL. Sprites not listed here get exactly the actions their tags define.
KNOWN_SPRITES = {
    "player": (
        ["idle", "walk", "dodge", "hurt", "light1", "light2", "light3", "light4", "finisher", "heavy1", "heavy2"],
        ["lunge"],
    ),
    "dummy": (["idle", "hurt"], []),
}


def read_defines(path: Path, prefix: str) -> dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(rf"\s*#define\s+({prefix}\w*)\s+(\d+)\b", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


# --- model ---------------------------------------------------------------------------------------


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int


@dataclass
class Frame:
    parts: list[tuple[int, int]]  # (dy, dx) of each OBJ, relative to the pivot
    tiles: bytes  # 32 bytes (top, bottom 8x8 tile) per part
    hitbox: Box | None
    hurtbox: Box


@dataclass
class Anim:
    tag: str
    action: str
    frames: list[Frame]
    ends: list[int]
    hit_frame: int | None  # 0-based
    loop: bool

    @property
    def symbol(self) -> str:
        return self.tag

    def size_estimate(self) -> int:
        return sum(len(f.tiles) + 4 * (len(f.parts) + 1) + 13 + 2 for f in self.frames) + 7


@dataclass
class Sprite:
    name: str
    source: str
    actions: list[str]
    # slot[action index][facing index] -> Anim or None
    slots: list[list[Anim | None]] = field(default_factory=list)


@dataclass
class TagData:
    dur_n: int
    dur_d: int
    hit: int | None
    loop: bool
    optional: bool


# --- parsing -------------------------------------------------------------------------------------


def parse_tag_data(text: str, tag: str, source: Path) -> TagData:
    """User data like `dur=1/8 hit=2 loop optional` (whitespace or newline separated)."""
    dur = hit = None
    loop = optional = False
    for tok in (text or "").split():
        if tok == "loop":
            loop = True
        elif tok == "optional":
            optional = True
        elif m := re.fullmatch(r"dur=(\d+)(?:/(\d+))?", tok):
            dur = (int(m.group(1)), int(m.group(2) or 1))
            if dur[0] == 0 or dur[1] == 0:
                raise ConvertError(source, f"tag {tag}: `{tok}` must be a positive fraction like dur=1/8")
        elif m := re.fullmatch(r"hit=(\d+)", tok):
            hit = int(m.group(1))
        else:
            raise ConvertError(source, f"tag {tag}: unknown user data `{tok}`; known: dur=<n>/<d> hit=<frame> loop optional")
    if dur is None:
        raise ConvertError(source, f"tag {tag}: no dur=; set the tag's user data to e.g. `dur=1/8` "
                                   f"(the musical length of the whole tag; 1/4 = one beat)")
    return TagData(dur[0], dur[1], hit, loop, optional)


def split_tag(tag: str, source: Path) -> tuple[str, int | None]:
    """`light1_se` -> ("light1", FACING index); `idle` -> ("idle", None) = same art for every facing."""
    m = TAG_RE.match(tag)
    if not m:
        raise ConvertError(source, f"tag {tag}: name must be <action>_<facing>, lowercase letters/digits, "
                                   f"facing one of {' '.join(FACINGS)}")
    action, facing = m.groups()
    if facing is None:
        return action, None
    if facing in FACINGS:
        return action, FACINGS.index(facing)
    if facing in MIRRORED:
        raise ConvertError(source, f"tag {tag}: {facing.upper()} is drawn by flipping {MIRRORED[facing].upper()} "
                                   f"at runtime; delete this tag and draw {action}_{MIRRORED[facing]}")
    raise ConvertError(source, f"tag {tag}: unknown facing `{facing}`; use one of {' '.join(FACINGS)}, "
                               f"or no suffix for an action with a single drawn facing")


def split_ticks(total: int, ms: list[int], tag: str, source: Path) -> list[int]:
    """Cumulative end tick of every frame; the frames share `total` ticks by their Aseprite durations."""
    weight = sum(ms)
    if weight <= 0:
        raise ConvertError(source, f"tag {tag}: frame durations add up to 0 ms; give the frames durations")
    ends, acc = [], 0
    for m in ms:
        acc += m
        ends.append((total * acc * 2 + weight) // (2 * weight))  # round half up
    ends[-1] = total
    prev = 0
    for i, e in enumerate(ends):
        if e <= prev:
            raise ConvertError(source, f"tag {tag} frame {i + 1}: would last 0 ticks of the tag's {total}; "
                                       f"lengthen dur, give the frame a longer duration, or remove frames")
        prev = e
    return ends


class SliceSet:
    """Slices from the JSON. `<kind>:<tag>` overrides `<kind>` for that tag (docs/sprites.md)."""

    def __init__(self, raw: list[dict]):
        self.by_name: dict[str, list[tuple[int, Box]]] = {}
        for s in raw:
            keys = sorted((k["frame"], Box(**{n: k["bounds"][n] for n in "xywh"})) for k in s.get("keys", []))
            self.by_name[s["name"]] = keys

    def at(self, kind: str, tag: str, frame: int) -> Box | None:
        for name in (f"{kind}:{tag}", kind):
            live = [b for f, b in self.by_name.get(name, []) if f <= frame]
            if live:
                return live[-1]
        return None


# --- conversion ----------------------------------------------------------------------------------


def to_grid(img: Image.Image, source: Path):
    """Shade 0-3 per pixel. Indexed sheets keep their indices (checked per tile later)."""
    w, h = img.size
    if img.mode == "P":
        px = img.load()
        return [[px[x, y] for x in range(w)] for y in range(h)], True
    return shades(img, source), False


def rel_box(b: Box, pivot: tuple[int, int], what: str, where: str, source: Path) -> Box:
    x, y = b.x - pivot[0], b.y - pivot[1]
    if not (-128 <= x <= 127 and -128 <= y <= 127 and 0 < b.w <= 255 and 0 < b.h <= 255):
        raise ConvertError(source, f"{where}: {what} at ({b.x},{b.y}) {b.w}x{b.h} is too far from the pivot")
    return Box(x, y, b.w, b.h)


def convert(png: Path, js: Path, budgets: dict[str, int], beat_ticks: int, name: str | None = None) -> Sprite:
    name = name or asset_name(Path(png.stem))
    source = Path(f"{png.stem}.aseprite")
    if not NAME_RE.match(name):
        raise ConvertError(source, f"sprite name `{name}` must be lowercase letters, digits and underscores")
    try:
        doc = json.loads(js.read_text())
        img = Image.open(png)
        img.load()
    except (OSError, ValueError) as e:
        raise ConvertError(source, f"cannot read the export {png.name}/{js.name} ({e}); {_STALE_HINT}") from e

    frames_raw = doc["frames"]
    if isinstance(frames_raw, dict):
        frames_raw = list(frames_raw.values())
    meta = doc["meta"]
    if not frames_raw:
        raise ConvertError(source, "has no frames")
    cw, ch = frames_raw[0]["sourceSize"]["w"], frames_raw[0]["sourceSize"]["h"]
    for i, f in enumerate(frames_raw):
        if f["trimmed"] or f["sourceSize"] != {"w": cw, "h": ch} or f["frame"]["w"] != cw or f["frame"]["h"] != ch:
            raise ConvertError(source, f"frame {i + 1}: sheet export is trimmed or resized; export without trim")

    # Budgets: the player has its own; every other character is enemy-sized.
    kind = "PLAYER" if name == "player" else "ENEMY"
    max_w, max_h = budgets[f"BUDGET_{kind}_W"], budgets[f"BUDGET_{kind}_H"]
    max_objs = budgets.get(f"BUDGET_{kind}_OBJS", (max_w // 8) * (max_h // 16))
    obj_budget = f"BUDGET_{kind}_OBJS" if f"BUDGET_{kind}_OBJS" in budgets else f"BUDGET_{kind}_W x BUDGET_{kind}_H"
    max_tiles = budgets["BUDGET_FRAME_TILES"]
    if cw > max_w or ch > max_h:
        raise ConvertError(source, f"canvas is {cw}x{ch}, budget is {max_w}x{max_h} (BUDGET_{kind}_W/H); "
                                   f"resize the canvas (Sprite > Canvas Size)")
    if cw % 8 or ch % 16:
        raise ConvertError(source, f"canvas is {cw}x{ch}; width must be a multiple of 8 and height of 16 "
                                   f"(8x16 sprites); resize the canvas (Sprite > Canvas Size)")

    grid, indexed = to_grid(img, source)
    slices = SliceSet(meta.get("slices", []))

    # Tags -> anims, grouped by action.
    by_action: dict[str, dict[int | None, Anim]] = {}
    optional_actions: set[str] = set()
    for t in meta.get("frameTags", []):
        tag = t["name"]
        action, facing = split_tag(tag, source)
        if t.get("direction", "forward") != "forward":
            raise ConvertError(source, f"tag {tag}: direction is {t['direction']}; only forward is supported "
                                       f"(draw the frames in order)")
        td = parse_tag_data(t.get("data", ""), tag, source)
        if td.optional:
            optional_actions.add(action)
        first, last = t["from"], t["to"]
        n = last - first + 1
        total_num = 4 * beat_ticks * td.dur_n
        if total_num % td.dur_d:
            raise ConvertError(source, f"tag {tag}: dur={td.dur_n}/{td.dur_d} is not a whole number of song ticks "
                                       f"({beat_ticks} per beat); use e.g. 1/4, 1/8, 1/16, 1/12, 1/32")
        total = total_num // td.dur_d
        if total > 0xFFFF:
            raise ConvertError(source, f"tag {tag}: dur={td.dur_n}/{td.dur_d} is {total} ticks; the maximum is 65535")
        if td.hit is not None and not 1 <= td.hit <= n:
            raise ConvertError(source, f"tag {tag}: hit={td.hit} but the tag has {n} frame(s); hit is 1-{n}")
        ends = split_ticks(total, [frames_raw[g]["duration"] for g in range(first, last + 1)], tag, source)

        frames = []
        for k, g in enumerate(range(first, last + 1)):
            where = f"tag {tag} frame {k + 1}"
            frames.append(build_frame(grid, indexed, frames_raw[g]["frame"], g, tag, where, slices,
                                      is_hit=(td.hit == k + 1), cw=cw, ch=ch, source=source,
                                      limits=(max_tiles, max_objs, obj_budget)))
        anim = Anim(tag, action, frames, ends, None if td.hit is None else td.hit - 1, td.loop)
        slot = by_action.setdefault(action, {})
        if facing in slot:
            raise ConvertError(source, f"tag {tag}: defined twice")
        if None in slot or (facing is None and slot):
            raise ConvertError(source, f"action {action}: mixes `{action}` (all facings) with per-facing tags; "
                                       f"use one or the other")
        slot[facing] = anim

    # Action list and completeness.
    required, optional = KNOWN_SPRITES.get(name, ([], []))
    for a in required:
        if a not in by_action:
            raise ConvertError(source, f"no tags for action `{a}`; draw {', '.join(f'{a}_{f}' for f in FACINGS)}")
    actions = required + optional + sorted(a for a in by_action if a not in required + optional)
    spr = Sprite(name, str(source), actions)
    for a in actions:
        slot = by_action.get(a, {})
        row: list[Anim | None] = []
        for fi, f in enumerate(FACINGS):
            if None in slot:
                row.append(slot[None])
            elif fi in slot:
                row.append(slot[fi])
            else:
                if a not in optional and a not in optional_actions:
                    raise ConvertError(source, f"missing tag {a}_{f}; draw it, or add the user data `optional` to "
                                               f"the {a} tags if the runtime may skip missing facings")
                row.append(None)
        spr.slots.append(row)
    return spr


_STALE_HINT = "run make with Aseprite installed and commit exports/"


def build_frame(grid, indexed, rect, gframe, tag, where, slices, is_hit, cw, ch, source, limits) -> Frame:
    fx, fy = rect["x"], rect["y"]
    max_tiles, max_objs, obj_budget = limits
    parts, tiles = [], bytearray()
    for ty in range(0, ch, 16):
        for tx in range(0, cw, 8):
            if indexed:
                for oy in (0, 8):
                    block = [grid[fy + ty + oy + y][fx + tx + x] for y in range(8) for x in range(8)]
                    bad = max(block)
                    if bad > 3:
                        raise ConvertError(source, f"{where}: tile ({tx},{ty + oy}) uses palette index {bad}; sprites "
                                                   f"have 4 shades (index 0 = transparent, 1-3); repaint with the "
                                                   f"first four palette colours")
            top = tile_bytes(grid, fx + tx, fy + ty)
            bottom = tile_bytes(grid, fx + tx, fy + ty + 8)
            if top == bytes(16) and bottom == bytes(16):
                continue  # fully transparent part: no OBJ, no tiles
            parts.append((tx, ty))
            tiles += top + bottom
    if not parts:
        raise ConvertError(source, f"{where}: the frame is empty; draw something on it or remove the frame")
    if len(parts) * 2 > max_tiles:
        raise ConvertError(source, f"{where}: {len(parts) * 2} tiles, budget is {max_tiles} (BUDGET_FRAME_TILES); "
                                   f"trim the frame")
    if len(parts) > max_objs:
        raise ConvertError(source, f"{where}: {len(parts)} OBJs, budget is {max_objs} ({obj_budget}); "
                                   f"trim the frame")

    pb = slices.at("pivot", tag, gframe)
    if pb is None:
        raise ConvertError(source, f"{where}: no `pivot` slice; add a 1x1 slice named pivot at the character's feet")
    pivot = (pb.x + pb.w // 2, pb.y + pb.h - 1)  # bottom centre of the slice
    hb = slices.at("hurtbox", tag, gframe)
    if hb is None:
        raise ConvertError(source, f"{where}: no `hurtbox` slice; add a slice named hurtbox around the body")
    hurt = rel_box(hb, pivot, "hurtbox", where, source)
    hit = None
    if is_hit:
        xb = slices.at("hitbox", tag, gframe)
        if xb is None:
            raise ConvertError(source, f"{where}: hit frame has no `hitbox` slice; add a slice named hitbox "
                                       f"(or hitbox:{tag}) that is live on this frame")
        hit = rel_box(xb, pivot, "hitbox", where, source)
    rel = [(ty - pivot[1], tx - pivot[0]) for tx, ty in parts]
    for dy, dx in rel:
        if not (-127 <= dy <= 127 and -127 <= dx <= 127):
            raise ConvertError(source, f"{where}: pivot ({pivot[0]},{pivot[1]}) is too far from the art")
    return Frame(rel, bytes(tiles), hit, hurt)


# --- C output ------------------------------------------------------------------------------------

BANNER = "/* Generated from {src} by tools/gbtools/sprites.py. Do not edit. */\n"


def c_box(b: Box | None) -> str:
    return "{ 0, 0, 0, 0 }" if b is None else f"{{ {b.x}, {b.y}, {b.w}, {b.h} }}"


def render_header(spr: Sprite) -> str:
    n = spr.name.upper()
    enum = "".join(f"    SPRITE_{n}_{a.upper()},\n" for a in spr.actions)
    return (BANNER.format(src=spr.source)
            + f"#ifndef GEN_SPRITE_{n}_H\n#define GEN_SPRITE_{n}_H\n\n"
            + '#include <gbdk/platform.h>\n#include "gb/spritedata.h"\n\n'
            + "/* Actions: index (action * DRAWN_FACINGS + drawn facing) into sprite_t.anims and *_anim_bank. */\n"
            + f"enum {{\n{enum}    SPRITE_{n}_ACTION_COUNT\n}};\n\n"
            + "/* The sprite data is split over several ROM banks when it does not fit in one. sprite_t, its\n"
            + " * anim table and the bank table live in BANK(sprite_<name>); each anim (sprite_anim_t, frames,\n"
            + " * ends, tiles, metasprites) lives in the bank given by its entry of *_anim_bank, which is\n"
            + " * 0 for a NULL anim. To use an anim: SWITCH_ROM(BANK(sprite_<name>)); read anims[i] and\n"
            + " * anim_bank[i].bank; SWITCH_ROM(that bank); read the sprite_anim_t. */\n"
            + "#ifndef GEN_SPRITE_BANK_T\n#define GEN_SPRITE_BANK_T\ntypedef struct { uint8_t bank; } sprite_bank_t;\n#endif\n\n"
            + f"BANKREF_EXTERN(sprite_{spr.name})\n"
            + f"extern const sprite_t sprite_{spr.name};\n"
            + f"extern const sprite_bank_t sprite_{spr.name}_anim_bank[];\n\n#endif\n")


def render_anim(spr: Sprite, anim: Anim, pools: dict) -> str:
    """C for one anim; tiles/metasprite pools are shared inside the file via `pools`."""
    out = []
    frame_lines = []
    for i, f in enumerate(anim.frames):
        tkey, pkey = f.tiles, tuple(f.parts)
        if tkey not in pools["tiles"]:
            idx = len(pools["tiles"])
            pools["tiles"][tkey] = f"t{idx}"
            rows = "".join("    " + ", ".join(f"0x{b:02X}" for b in tkey[o:o + 16]) + ",\n"
                           for o in range(0, len(tkey), 16))
            pools["text"].append(f"static const uint8_t t{idx}[] = {{\n{rows}}};\n")
        if pkey not in pools["parts"]:
            idx = len(pools["parts"])
            pools["parts"][pkey] = f"p{idx}"
            items = "".join(f"    METASPR_ITEM({dy}, {dx}, {2 * k}, 0),\n" for k, (dy, dx) in enumerate(f.parts))
            pools["text"].append(f"static const metasprite_t p{idx}[] = {{\n{items}    METASPR_TERM\n}};\n")
        frame_lines.append(f"    {{ {pools['tiles'][tkey]}, {pools['parts'][pkey]}, {len(f.parts) * 2}, "
                           f"{c_box(f.hitbox)}, {c_box(f.hurtbox)} }},\n")
    out.append(f"static const sprite_frame_t f_{anim.symbol}[] = {{\n{''.join(frame_lines)}}};\n")
    out.append(f"static const uint16_t e_{anim.symbol}[] = {{ {', '.join(map(str, anim.ends))} }};\n")
    hit = ANIM_NO_HIT if anim.hit_frame is None else str(anim.hit_frame)
    out.append(f"const sprite_anim_t sprite_{spr.name}_anim_{anim.symbol} = {{ f_{anim.symbol}, e_{anim.symbol}, "
               f"{len(anim.frames)}, {hit}, {'ANIM_LOOP' if anim.loop else '0'} }};\n")
    return "\n".join(out)


def unique_anims(spr: Sprite) -> list[Anim]:
    seen, out = set(), []
    for row in spr.slots:
        for a in row:
            if a is not None and a.tag not in seen:
                seen.add(a.tag)
                out.append(a)
    return out


def assign_banks(spr: Sprite) -> dict[str, int]:
    """Anim tag -> file index (0 = sprite_<name>.c). Greedy, in tag order."""
    index_size = 16 + 3 * sum(len(r) for r in spr.slots)
    used = [index_size] + [0] * (BANK_FILES - 1)
    where, cur = {}, 0
    for a in unique_anims(spr):
        size = a.size_estimate()
        if size > BANK_CAP - index_size:
            raise ConvertError(Path(spr.source), f"tag {a.tag}: its data is ~{size} bytes, more than one ROM bank "
                                                 f"holds; reduce its frames or tiles")
        while used[cur] + size > BANK_CAP:
            cur += 1
            if cur >= BANK_FILES:
                total = sum(x.size_estimate() for x in unique_anims(spr))
                raise ConvertError(Path(spr.source), f"sprite data is ~{total} bytes; the converter supports "
                                                     f"{BANK_FILES} ROM banks ({BANK_FILES * BANK_CAP} bytes); "
                                                     f"remove frames, shrink the art, or ask for more banks")
        used[cur] += size
        where[a.tag] = cur
    return where


def bank_ref(spr: Sprite, k: int) -> str:
    return f"sprite_{spr.name}" if k == 0 else f"sprite_{spr.name}_b{k}"


def render_sources(spr: Sprite) -> dict[str, str]:
    where = assign_banks(spr)
    files: dict[str, str] = {}
    n = spr.name
    for k in range(BANK_FILES):
        fname = f"sprite_{n}.c" if k == 0 else f"spritebank_{n}_{k}.c"
        anims = [a for a in unique_anims(spr) if where[a.tag] == k]
        head = BANNER.format(src=spr.source) + f'#pragma bank 255\n\n#include <gbdk/platform.h>\n#include "sprite_{n}.h"\n\n'
        if k > 0:
            head += f"BANKREF({bank_ref(spr, k)})\n\n"
        if not anims and k > 0:
            files[fname] = head + "/* no anims in this bank */\n"
            continue
        pools = {"tiles": {}, "parts": {}, "text": []}
        anim_text = [render_anim(spr, a, pools) for a in anims]
        body = "\n".join(pools["text"]) + "\n" + "\n".join(anim_text)
        if k == 0:
            body = "BANKREF(sprite_%s)\n\n" % n + body + "\n" + render_index(spr, where)
        files[fname] = head + body
    return files


def render_index(spr: Sprite, where: dict[str, int]) -> str:
    n = spr.name
    used = sorted({where[a.tag] for a in unique_anims(spr)} - {0})
    out = "".join(f"BANKREF_EXTERN({bank_ref(spr, k)})\n" for k in used)
    for a in unique_anims(spr):
        if where[a.tag] != 0:
            out += f"extern const sprite_anim_t sprite_{n}_anim_{a.symbol};\n"
    flat = [(a, f) for a, row in zip(spr.actions, spr.slots) for f in row]
    ptrs = ",\n".join("    " + ("0" if an is None else f"&sprite_{n}_anim_{an.symbol}") for _, an in flat)
    banks = ",\n".join("    { " + ("0" if an is None else f"BANK({bank_ref(spr, where[an.tag])})") + " }"
                       for _, an in flat)
    count = len(flat)
    return (out + f"\nstatic const sprite_anim_t *const anim_table[{count}] = {{\n{ptrs}\n}};\n\n"
            + f"const sprite_bank_t sprite_{n}_anim_bank[{count}] = {{\n{banks}\n}};\n\n"
            + f"const sprite_t sprite_{n} = {{ anim_table, SPRITE_{n.upper()}_ACTION_COUNT, BANK(sprite_{n}) }};\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbtools.sprites")
    ap.add_argument("png", type=Path)
    ap.add_argument("json", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    ap.add_argument("--beat", type=Path, default=DEFAULT_BEAT)
    args = ap.parse_args(argv)
    try:
        budgets = read_defines(args.budgets, "BUDGET_")
        beat_ticks = read_defines(args.beat, "BEAT_TICKS").get("BEAT_TICKS", 48)
        spr = convert(args.png, args.json, budgets, beat_ticks)
        header, sources = render_header(spr), render_sources(spr)
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"{args.json}: missing {e} (is this an Aseprite --format json-array export with tags and slices?)",
              file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"sprite_{spr.name}.h").write_text(header)  # first: make's primary target
    for fname, text in sources.items():
        (args.out_dir / fname).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
