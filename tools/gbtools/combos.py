"""Convert data/combos.toml into build/gen/combos.{h,c} and combos.lab.json (ADR 0004, 0008).

    python -m gbtools.combos <combos.toml> <out_dir>

Every string is stored as COMBO_MAX_STEPS fixed-size step and attack slots so the feel lab can edit a
pattern in place. Step byte: bits 0-1 button (1 = A, 2 = B, 3 = rest, 0 = end), bits 2-3 held direction
(0 = any, 1 = forward, 2 = back, 3 = side; matches COMBO_DIR_* in src/core/combo.h). The matcher is
src/core/combo.c; the schema is documented at the top of data/combos.toml. A [[string]] may also set
`label`, its on-screen name (default: the name upper-cased, `_` as a space; at most LABEL_MAX columns of
the BG font), emitted as COMBO_STRING_LIST / COMBO_STRING_LABELS in combos.h for the combat UI.

DEBUG builds (and host tests) keep a RAM copy `combos` that `combos_reset()` fills from the ROM
defaults; release builds read the ROM table directly and `combos_reset()` is a no-op macro.
"""

import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from gbtools import labdesc
from gbtools.errors import ConvertError
from gbtools.names import IDENT, display_name, label_problem

MAX_STEPS = 8
MAX_STRINGS = 8  # src/core/combo.c tracks candidate strings in one byte
NONE = 0xFF
LABEL_MAX = 12  # columns the combat UI gives a string's on-screen name
RESERVED = {"count"}

END, REST = 0x00, 0x03
BUTTONS = {"A": 0x01, "B": 0x02}
DIRS = {"": 0, "f": 1, "b": 2, "s": 3}
TOKENS = {"-": END, ".": REST} | {
    d + b: code | (dcode << 2) for d, dcode in DIRS.items() for b, code in BUTTONS.items()
}

ATTACK_KEYS = ["name", "anim", "damage", "lunge", "sfx"]
STRING_KEYS = ["name", "label", "steps", "attacks", "unlock"]
DAMAGE = (0, 99)
LUNGE = (0, 48)
UNLOCK = (0, 255)

STRING_SIZE = 2 * MAX_STEPS + 1  # steps[], attacks[], unlock
ATTACK_SIZE = 4  # anim, damage, lunge, sfx


@dataclass
class Attack:
    name: str
    anim: int  # index into Combos.anims
    damage: int
    lunge: int
    sfx: int  # index into Combos.sfx, or NONE
    sfx_given: bool  # the TOML has an `sfx` key (the lab must add one to set it)


@dataclass
class String:
    name: str
    unlock: int
    steps: list[int]  # MAX_STEPS step codes
    attacks: list[int]  # MAX_STEPS attack indices, NONE under rests and ends
    tokens: list[str]  # the TOML step tokens, as written
    attack_names: list[str]  # the TOML attack names, as written
    label: str = ""  # on-screen name: `label`, or the name upper-cased with spaces for underscores


@dataclass
class Combos:
    attacks: list[Attack]
    strings: list[String]
    anims: list[str]
    sfx: list[str]


def _tables(path: Path, doc: dict, key: str) -> list[dict]:
    value = doc.get(key, [])
    if not isinstance(value, list) or not all(isinstance(t, dict) for t in value):
        raise ConvertError(path, f"'{key}' must be an array of [[{key}]] tables")
    if not value:
        raise ConvertError(path, f"no [[{key}]] tables; add at least one")
    return value


def _name(path: Path, kind: str, index: int, table: dict, seen: set[str]) -> str:
    name = table.get("name")
    if name is None:
        raise ConvertError(path, f'{kind} {index + 1} has no name; add name = "<lower_snake_case>"')
    if not isinstance(name, str) or not IDENT.match(name):
        raise ConvertError(path, f"{kind} name '{name}' must be lower_snake_case")
    if name in RESERVED:
        raise ConvertError(path, f"{kind} name '{name}' is reserved; pick another")
    if name in seen:
        raise ConvertError(path, f"{kind} '{name}' is defined twice; rename one")
    seen.add(name)
    return name


def _keys(path: Path, where: str, table: dict, allowed: list[str]) -> None:
    for key in table:
        if key not in allowed:
            raise ConvertError(path, f"{where}: unknown key '{key}'; allowed: {', '.join(allowed)}")


def _int(path: Path, where: str, table: dict, key: str, bounds: tuple[int, int], default=None) -> int:
    if key not in table:
        if default is None:
            raise ConvertError(path, f"{where}: missing {key}; add {key} = <{bounds[0]}..{bounds[1]}>")
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConvertError(path, f"{where}: {key} must be an integer in [{bounds[0]}..{bounds[1]}]")
    if not bounds[0] <= value <= bounds[1]:
        raise ConvertError(path, f"{where}: {key} = {value} is out of range [{bounds[0]}..{bounds[1]}]")
    return value


def _index(names: list[str], name: str) -> int:
    if name not in names:
        names.append(name)
    return names.index(name)


def _parse_attacks(path: Path, tables: list[dict], anims: list[str], sfx: list[str]) -> list[Attack]:
    attacks, seen = [], set()
    for i, t in enumerate(tables):
        name = _name(path, "attack", i, t, seen)
        where = f"attack '{name}'"
        _keys(path, where, t, ATTACK_KEYS)
        anim = t.get("anim")
        if anim is None:
            raise ConvertError(path, f'{where}: missing anim; add anim = "<player animation, e.g. light1>"')
        if not isinstance(anim, str) or not IDENT.match(anim):
            raise ConvertError(
                path, f"{where}: anim '{anim}' must be lower_snake_case (the action of an Aseprite tag)")
        damage = _int(path, where, t, "damage", DAMAGE)
        lunge = _int(path, where, t, "lunge", LUNGE, default=0)
        effect = t.get("sfx", "")
        if not isinstance(effect, str):
            raise ConvertError(path, f'{where}: sfx must be a sound effect name like "swing", or "" for none')
        if effect and not IDENT.match(effect):
            raise ConvertError(path, f"{where}: sfx '{effect}' must be lower_snake_case (assets/sfx/<sfx>.toml)")
        attacks.append(Attack(
            name, _index(anims, anim), damage, lunge, _index(sfx, effect) if effect else NONE, "sfx" in t))
    return attacks


def _parse_string(path: Path, i: int, t: dict, seen: set[str], attack_names: list[str]) -> String:
    name = _name(path, "string", i, t, seen)
    where = f"string '{name}'"
    _keys(path, where, t, STRING_KEYS)
    for key, example in (("steps", '["A", "A", ".", "A"]'), ("attacks", '["jab1", "jab2", "", "wide"]')):
        if key not in t:
            raise ConvertError(path, f"{where}: missing {key}; add {key} = {example}")
    tokens, names = t["steps"], t["attacks"]
    if not isinstance(tokens, list) or not all(isinstance(s, str) for s in tokens):
        raise ConvertError(path, f'{where}: steps must be an array of step strings, e.g. ["A", "A", ".", "A"]')
    if not isinstance(names, list) or not all(isinstance(s, str) for s in names):
        raise ConvertError(
            path, f'{where}: attacks must be an array of attack names, e.g. ["jab1", "jab2", "", "wide"]')
    unlock = _int(path, where, t, "unlock", UNLOCK, default=0)
    label = _label(path, where, t, name)
    if len(tokens) > MAX_STEPS:
        raise ConvertError(path, f"{where}: {len(tokens)} steps, at most {MAX_STEPS} fit; shorten it")
    if len(names) > len(tokens):
        raise ConvertError(path, f"{where}: {len(names)} attacks for {len(tokens)} steps; give one per step")

    steps, attacks = [END] * MAX_STEPS, [NONE] * MAX_STEPS
    ended = False
    for k, token in enumerate(tokens):
        at = f"{where} step {k + 1}"
        if token not in TOKENS:
            raise ConvertError(
                path, f"{at}: unknown step '{token}'; use A or B, optionally after f/b/s (forward/back/side) "
                "as in fB, '.' for a rest or '-' to pad the end")
        code = TOKENS[token]
        if ended and code != END:
            raise ConvertError(path, f"{at}: '{token}' after '-'; '-' may only pad the end")
        ended = ended or code == END
        steps[k] = code
        attack = names[k] if k < len(names) else ""
        if code in (END, REST):
            if attack:
                raise ConvertError(
                    path, f"{at} ('{token}'): rests and '-' have no attack; make entry {k + 1} of attacks \"\"")
            continue
        if not attack:
            raise ConvertError(path, f"{at} ('{token}') has no attack; add one as entry {k + 1} of attacks")
        if attack not in attack_names:
            raise ConvertError(
                path, f"{at}: unknown attack '{attack}'; define it in an [[attack]] or use one of "
                + ", ".join(attack_names))
        attacks[k] = attack_names.index(attack)

    used = [c for c in steps if c != END]
    if not used:
        raise ConvertError(path, f"{where} has no steps; add at least one A or B")
    if used[0] == REST:
        raise ConvertError(path, f"{where} step 1: a string can't start with a rest; remove the leading '.'")
    if used[-1] == REST:
        raise ConvertError(
            path, f"{where} step {len(used)}: a string can't end with a rest; remove the trailing '.' "
            "(string_grace already lets the player pause)")
    return String(name, unlock, steps, attacks, list(tokens), list(names), label)


def _label(path: Path, where: str, t: dict, name: str) -> str:
    """The string's on-screen name, printed with the BG font (src/gb/text.h)."""
    default = display_name(name)
    if "label" not in t:
        if problem := label_problem(default, LABEL_MAX):
            raise ConvertError(path, f"{where}: its on-screen name '{default}' (the name upper-cased) {problem}; "
                                     f'add a shorter label, e.g. label = "{default[:LABEL_MAX].rstrip()}"')
        return default
    label = t["label"]
    if problem := label_problem(label, LABEL_MAX):
        shown = f"'{label}'" if isinstance(label, str) else repr(label)
        fix = "change it" if label_problem(default, LABEL_MAX) else f"change it, or remove label to show '{default}'"
        raise ConvertError(path, f"{where}: label {shown} {problem}; {fix}")
    return label


def _length(s: String) -> int:
    return sum(1 for c in s.steps if c != END)


def _check_ambiguity(path: Path, strings: list[String], attack_names: list[str]) -> None:
    """The matcher keeps strings with identical steps alive together, so it must be able to tell them
    apart before one ends, and they must agree on what each shared step does."""
    for a in strings:
        n = _length(a)
        for b in strings:
            if b is not a and _length(b) >= n and a.steps[:n] == b.steps[:n]:
                raise ConvertError(
                    path, f"string '{a.name}' is the start of string '{b.name}' (same steps), so the matcher "
                    f"can't tell when '{a.name}' ends; make their steps differ before '{a.name}' ends")
    for i, a in enumerate(strings):
        for b in strings[i + 1:]:
            for k in range(MAX_STEPS):
                if a.steps[k] != b.steps[k]:
                    break
                if a.attacks[k] != b.attacks[k]:
                    raise ConvertError(
                        path, f"strings '{a.name}' and '{b.name}' start with the same steps, but step {k + 1} "
                        f"is attack '{attack_names[a.attacks[k]]}' in '{a.name}' and "
                        f"'{attack_names[b.attacks[k]]}' in '{b.name}'; use the same attack until their "
                        "steps differ")


def parse(path: Path) -> Combos:
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConvertError(path, f"invalid TOML: {e}") from e
    for key in doc:
        if key not in ("attack", "string"):
            raise ConvertError(path, f"unknown top-level key '{key}'; use [[attack]] and [[string]] tables")

    anims: list[str] = []
    sfx: list[str] = []
    attacks = _parse_attacks(path, _tables(path, doc, "attack"), anims, sfx)
    attack_names = [a.name for a in attacks]
    string_tables = _tables(path, doc, "string")
    if len(string_tables) > MAX_STRINGS:
        raise ConvertError(
            path, f"{len(string_tables)} strings, at most {MAX_STRINGS} fit (the matcher tracks candidates "
            "in one byte); remove one")
    seen: set[str] = set()
    strings = [_parse_string(path, i, t, seen, attack_names) for i, t in enumerate(string_tables)]
    _check_ambiguity(path, strings, attack_names)
    return Combos(attacks, strings, anims, sfx)


# --- output ------------------------------------------------------------------------------------


def _enum(prefix: str, names: list[str]) -> str:
    body = "".join(f"    {prefix}_{n.upper()},\n" for n in names)
    return f"enum {{\n{body}    {prefix}_COUNT\n}};\n"


def _bytes(values: list[int]) -> str:
    return "{ " + ", ".join(f"0x{v:02X}" for v in values) + " }"


def render(c: Combos, source: str) -> tuple[str, str, str]:
    banner = f"/* Generated from {source} by tools/gbtools/combos.py. Do not edit. */\n"
    attack_names = [a.name for a in c.attacks]
    anim_list = " ".join(f"X({n.upper()})" for n in c.anims)
    string_list = " ".join(f'X({s.name.upper()}, "{s.label}")' for s in c.strings)
    string_labels = ", ".join(f'"{s.label}"' for s in c.strings)
    sfx_list = " ".join(f"X({n.upper()})" for n in c.sfx)
    header = (
        banner
        + "#ifndef GEN_COMBOS_H\n#define GEN_COMBOS_H\n\n#include <stdint.h>\n\n"
        + f"#define COMBO_MAX_STEPS {MAX_STEPS}\n\n"
        + "/* Step byte: bits 0-1 button (COMBO_A 1, COMBO_B 2), bits 2-3 held direction (COMBO_DIR_*;\n"
        + " * 0 = any). Button bits 3 = a rest, the whole byte 0 = end of the string. */\n"
        + "#define COMBO_STEP_END 0x00\n#define COMBO_STEP_REST 0x03\n#define COMBO_STEP_BUTTONS 0x03\n"
        + "#define COMBO_STEP_DIR_SHIFT 2\n"
        + f"#define COMBO_NO_ATTACK 0x{NONE:02X} /* attacks[] under rests and ends */\n"
        + f"#define COMBO_NO_SFX 0x{NONE:02X}\n\n"
        + "/* Strings, attacks (data/combos.toml order), and the player animations and sound effects the\n"
        + " * attacks name, in first-use order. Integration maps the last two to the sprite and sfx ids\n"
        + " * with the X-macro lists, e.g. #define M(n) SPRITE_PLAYER_##n, ... { COMBO_ANIM_LIST(M) }. */\n"
        + _enum("COMBO_STRING", [s.name for s in c.strings]) + "\n"
        + _enum("COMBO_ATTACK", attack_names) + "\n"
        + _enum("COMBO_ANIM", c.anims) + "\n"
        + _enum("COMBO_SFX", c.sfx) + "\n"
        + "/* On-screen string names (data/combos.toml `label`, else the name upper-cased), at most\n"
        + " * COMBO_LABEL_MAX columns of the BG font: X(NAME, \"LABEL\") in COMBO_STRING_* order. For a table:\n"
        + " * static const char *const names[COMBO_STRING_COUNT] = COMBO_STRING_LABELS; */\n"
        + f"#define COMBO_LABEL_MAX {LABEL_MAX}\n"
        + f"#define COMBO_STRING_LIST(X) {string_list}\n"
        + f"#define COMBO_STRING_LABELS {{ {string_labels} }}\n\n"
        + f"#define COMBO_ANIM_LIST(X) {anim_list}\n"
        + f"#define COMBO_SFX_LIST(X) {sfx_list}\n\n"
        + "typedef struct {\n"
        + "    uint8_t steps[COMBO_MAX_STEPS];   /* step bytes, COMBO_STEP_END-padded */\n"
        + "    uint8_t attacks[COMBO_MAX_STEPS]; /* COMBO_ATTACK_* per step, COMBO_NO_ATTACK under rests */\n"
        + "    uint8_t unlock;                   /* progression level that unlocks it (not enforced yet) */\n"
        + "} combo_string_t;\n\n"
        + "typedef struct {\n"
        + "    uint8_t anim;   /* COMBO_ANIM_* */\n"
        + "    uint8_t damage;\n"
        + "    uint8_t lunge;  /* px the soft lock may move toward the target */\n"
        + "    uint8_t sfx;    /* COMBO_SFX_* or COMBO_NO_SFX */\n"
        + "} combo_attack_t;\n\n"
        + f"#define COMBO_STRING_SIZE {STRING_SIZE} /* the lab descriptor's offsets assume these sizes */\n"
        + f"#define COMBO_ATTACK_SIZE {ATTACK_SIZE}\n\n"
        + "typedef struct {\n"
        + "    combo_string_t strings[COMBO_STRING_COUNT];\n"
        + "    combo_attack_t attacks[COMBO_ATTACK_COUNT];\n"
        + "} combos_t;\n\n"
        + "/* DEBUG builds and host tests: a RAM copy the feel lab edits (symbol _combos). */\n"
        + "#if defined(DEBUG) || !defined(__SDCC)\n"
        + "#define COMBOS_IN_RAM 1\n"
        + "extern const combos_t combos_defaults;\n"
        + "extern combos_t combos;\n"
        + "void combos_reset(void);\n"
        + "#else\n"
        + "extern const combos_t combos;\n"
        + "#define combos_reset() ((void)0)\n"
        + "#endif\n\n#endif\n"
    )

    rows = []
    for s in c.strings:
        rows.append(f"        {{ /* {s.name} */\n            {_bytes(s.steps)},\n"
                    f"            {_bytes(s.attacks)},\n            {s.unlock}\n        }},\n")
    attack_rows = [
        f"        {{ {a.anim}, {a.damage}, {a.lunge}, 0x{a.sfx:02X} }}, /* {a.name} */\n" for a in c.attacks]
    table = "{\n    {\n" + "".join(rows) + "    },\n    {\n" + "".join(attack_rows) + "    }\n};\n"
    source_c = (
        banner
        + '#include "combos.h"\n\n'
        + "#ifdef COMBOS_IN_RAM\n"
        + "const combos_t combos_defaults = " + table + "\n"
        + "combos_t combos;\n\n"
        + "void combos_reset(void)\n{\n    combos = combos_defaults;\n}\n"
        + "#else\n"
        + "const combos_t combos = " + table
        + "#endif\n"
    )
    return header, source_c, json.dumps(_lab(c, source), indent=1) + "\n"


def _lab(c: Combos, source: str) -> dict:
    step_values = {token: code for token, code in TOKENS.items()}
    attack_values = {"": NONE} | {a.name: i for i, a in enumerate(c.attacks)}
    fields = []
    for i, s in enumerate(c.strings):
        base = i * STRING_SIZE
        for k in range(MAX_STEPS):
            fields.append(labdesc.field(
                ["string", i, "steps", k], base + k, "enum", s.tokens[k] if k < len(s.tokens) else "-",
                f"{s.name} step {k + 1}: A/B (f/b/s = held direction), '.' rest, '-' end",
                values=step_values, absent=k >= len(s.tokens)))
        for k in range(MAX_STEPS):
            fields.append(labdesc.field(
                ["string", i, "attacks", k], base + MAX_STEPS + k, "enum",
                s.attack_names[k] if k < len(s.attack_names) else "", f"{s.name} step {k + 1}: attack ('' under rests)",
                values=attack_values, absent=k >= len(s.attack_names)))
        fields.append(labdesc.field(
            ["string", i, "unlock"], base + 2 * MAX_STEPS, "u8", s.unlock,
            f"{s.name}: progression level that unlocks it (not enforced yet)", min=UNLOCK[0], max=UNLOCK[1]))
    base = len(c.strings) * STRING_SIZE
    for j, a in enumerate(c.attacks):
        at = base + j * ATTACK_SIZE
        fields += [
            labdesc.field(["attack", j, "anim"], at, "enum", c.anims[a.anim], f"{a.name}: player animation",
                          values={n: i for i, n in enumerate(c.anims)}),
            labdesc.field(["attack", j, "damage"], at + 1, "u8", a.damage,
                          f"{a.name}: damage (OFFBEAT >> offbeat_damage_shift)", min=DAMAGE[0], max=DAMAGE[1]),
            labdesc.field(["attack", j, "lunge"], at + 2, "u8", a.lunge, f"{a.name}: soft-lock lunge, px",
                          min=LUNGE[0], max=LUNGE[1]),
            labdesc.field(["attack", j, "sfx"], at + 3, "enum", c.sfx[a.sfx] if a.sfx != NONE else "",
                          f"{a.name}: sound effect", values={"": NONE} | {n: i for i, n in enumerate(c.sfx)},
                          absent=not a.sfx_given),
        ]
    return {"source": source, "symbol": "_combos", "fields": fields}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m gbtools.combos <combos.toml> <out_dir>", file=sys.stderr)
        return 2
    src, out_dir = Path(argv[0]), Path(argv[1])
    try:
        header, source_c, lab = render(parse(src), src.as_posix())
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "combos.h").write_text(header)
    (out_dir / "combos.c").write_text(source_c)
    (out_dir / "combos.lab.json").write_text(lab)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
