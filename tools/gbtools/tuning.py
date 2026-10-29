"""Convert data/tuning.toml into build/gen/tuning.{h,c} and tuning.lab.json.

Each `[table] key = int` becomes an int16_t field `table_key` of `tuning_t`. The ROM keeps a mutable
copy (`tuning`) so the debug menu can change values live; `tuning_reset()` restores the defaults.

Every param's comment starts with its allowed range, `key = 3  # [0..10] what it does`. The range is
validated here and written, with the doc text, to build/gen/tuning.lab.json so the feel lab can build
a slider for it (ADR 0008).

The DEBUG debug menu (src/gb/debugmenu.c) lists every param from the X-macros in tuning.h, one page per
[table]. A param's menu label is its key, upper-cased and shortened to LABEL_MAX columns; to choose it,
put it in braces right after the range: `perfect_window = 3  # [0..10] {PERFECT} what it does`.
"""

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from gbtools import labdesc
from gbtools.errors import ConvertError
from gbtools.names import IDENT, display_name, label_problem, short_label

INT16_MIN, INT16_MAX = -32768, 32767
LABEL_MAX = 10  # debug menu label columns (src/gb/debugmenu.c)
TITLE_MAX = 12  # debug menu page title columns
TABLE_LINE = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")
PARAM_LINE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*[^#]*?(?:#(.*))?$")
RANGE = re.compile(r"^\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*(.*?)\s*$")
LABEL = re.compile(r"^\{([^{}]*)\}\s*(.*)$")


@dataclass
class Param:
    table: str
    key: str
    value: int
    min: int
    max: int
    doc: str
    label: str = ""

    @property
    def name(self) -> str:
        return f"{self.table}_{self.key}"


def parse(path: Path) -> list[tuple[str, int]]:
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConvertError(path, f"invalid TOML: {e}; fix the syntax at that line") from e

    fields: list[tuple[str, int]] = []
    owner: dict[str, str] = {}
    for table, entries in doc.items():
        if not isinstance(entries, dict):
            raise ConvertError(path, f"'{table}' must be a [table] of integer params; move it under one, "
                                     f"e.g. [timing]")
        if not IDENT.match(table):
            raise ConvertError(path, f"table name '{table}' must be lower_snake_case; rename it, "
                                     f"e.g. [{table.lower()}]")
        for key, value in entries.items():
            where = f"{table}.{key}"
            if not IDENT.match(key):
                raise ConvertError(path, f"'{where}' must be lower_snake_case; rename it, e.g. {key.lower()}")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConvertError(path, f"'{where}' must be an integer (use 0/1 for switches)")
            if not INT16_MIN <= value <= INT16_MAX:
                raise ConvertError(path, f"'{where}' = {value} does not fit in int16; use a value from "
                                         f"{INT16_MIN} to {INT16_MAX}")
            name = f"{table}_{key}"
            if name in owner:
                raise ConvertError(path, f"'{where}' and '{owner[name]}' both become the C field {name}; "
                                         f"rename one of them")
            owner[name] = where
            fields.append((name, value))
    return fields


def parse_params(path: Path) -> list[Param]:
    """`parse`, plus the `[min..max] {LABEL} doc` comment on each param's line. Raises ConvertError
    when a param has no range, the range is malformed, the default lies outside it, or the label
    can't be printed."""
    parse(path)  # type and range-of-int16 checks, with their messages
    doc = tomllib.loads(path.read_text())
    comments: dict[tuple[str, str], str | None] = {}
    table = ""
    for line in path.read_text().splitlines():
        if m := TABLE_LINE.match(line):
            table = m.group(1).strip()
        elif (m := PARAM_LINE.match(line)) and table:
            comments[(table, m.group(1))] = m.group(2)

    params = []
    items = [(table, key, value) for table, entries in doc.items() for key, value in entries.items()]
    for table, key, value in items:
        where = f"{table}.{key}"
        comment = comments.get((table, key))
        if comment is None or not (m := RANGE.match(comment)):
            raise ConvertError(
                path,
                f"'{where}' needs its allowed range at the start of its comment, e.g. "
                f"`{key} = {value}  # [0..10] what it does`; the feel lab builds its slider from it",
            )
        lo, hi, text = int(m.group(1)), int(m.group(2)), m.group(3)
        if lo > hi:
            raise ConvertError(path, f"'{where}' has range [{lo}..{hi}]; the minimum must not exceed the maximum, "
                                     f"so swap them")
        if not lo <= value <= hi:
            raise ConvertError(
                path, f"'{where}' = {value} is outside its range [{lo}..{hi}]; change the value or widen the range"
            )
        label = short_label(key, LABEL_MAX)
        if lm := LABEL.match(text):
            label, text = lm.group(1), lm.group(2)
            if problem := label_problem(label, LABEL_MAX):
                raise ConvertError(
                    path, f"'{where}': debug menu label {{{label}}} {problem}; fix it, or remove the "
                          f"{{...}} after the range to use '{short_label(key, LABEL_MAX)}'")
        same = next((q for q in params if q.table == table and q.label == label), None)
        if same:
            raise ConvertError(
                path, f"'{where}' and '{same.table}.{same.key}' share the debug menu label '{label}' on the "
                      f"[{table}] page; give one its own label after the range, e.g. `# [{lo}..{hi}] {{NAME}} ...`")
        params.append(Param(table, key, value, lo, hi, text, label))
    return params


def lab_descriptor(params: list[Param], source: str) -> str:
    """The build/gen/tuning.lab.json text (ADR 0008). `tuning_t` is int16 fields in file order."""
    fields = [
        labdesc.field([p.table, p.key], 2 * i, "i16", p.value, p.doc, min=p.min, max=p.max)
        for i, p in enumerate(params)
    ]
    head = json.dumps({"source": source, "symbol": "_tuning"})[:-1]
    return head + ', "fields": [\n  ' + ",\n  ".join(json.dumps(f) for f in fields) + "\n]}\n"


def _c_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def menu_macros(params: list[Param]) -> str:
    """X-macros the DEBUG debug menu builds its pages from (src/gb/debugmenu.c)."""
    rows = "".join(
        f" \\\n    X({p.name}, {_c_string(p.label)}, \"{p.table}.{p.key}\", {p.min}, {p.max})" for p in params)
    tables: list[tuple[str, int, int]] = []
    for i, p in enumerate(params):
        if tables and tables[-1][0] == p.table:
            name, first, count = tables[-1]
            tables[-1] = (name, first, count + 1)
        else:
            tables.append((p.table, i, 1))
    pages = "".join(
        f" \\\n    T({_c_string(short_label(t, TITLE_MAX))}, {first}, {count})" for t, first, count in tables)
    return (
        "/* Debug menu (src/gb/debugmenu.c), in file order. Labels fit TUNING_LABEL_MAX columns of the BG font.\n"
        " *   TUNING_PARAM_LIST(X): X(field, \"LABEL\", \"table.key\", min, max)\n"
        " *   TUNING_TABLE_LIST(T): T(\"TITLE\", first param index, param count), one per [table] */\n"
        f"#define TUNING_LABEL_MAX {LABEL_MAX}\n"
        f"#define TUNING_TITLE_MAX {TITLE_MAX}\n"
        f"#define TUNING_PARAM_COUNT {len(params)}\n"
        f"#define TUNING_TABLE_COUNT {len(tables)}\n"
        f"#define TUNING_PARAM_LIST(X){rows}\n"
        f"#define TUNING_TABLE_LIST(T){pages}\n"
    )


def render(params: list[Param], source: str) -> tuple[str, str]:
    banner = f"/* Generated from {source} by tools/gbtools/tuning.py. Do not edit. */\n"
    members = "".join(f"    int16_t {p.name};\n" for p in params)
    header = (
        banner
        + "#ifndef GEN_TUNING_H\n#define GEN_TUNING_H\n\n#include <stdint.h>\n\n"
        + "typedef struct {\n" + members + "} tuning_t;\n\n"
        + "extern const tuning_t tuning_defaults;\n"
        + "extern tuning_t tuning;\n\n"
        + "void tuning_reset(void);\n\n"
        + menu_macros(params)
        + "\n#endif\n"
    )
    values = "".join(f"    {p.value}, /* {p.name} */\n" for p in params)
    source_c = (
        banner
        + '#include "tuning.h"\n\n'
        + "const tuning_t tuning_defaults = {\n" + values + "};\n\n"
        + "tuning_t tuning;\n\n"
        + "void tuning_reset(void)\n{\n    tuning = tuning_defaults;\n}\n"
    )
    return header, source_c


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m gbtools.tuning <tuning.toml> <out_dir>", file=sys.stderr)
        return 2
    src, out_dir = Path(argv[0]), Path(argv[1])
    try:
        params = parse_params(src)
        header, source_c = render(params, src.as_posix())
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tuning.h").write_text(header)
    (out_dir / "tuning.c").write_text(source_c)
    (out_dir / "tuning.lab.json").write_text(lab_descriptor(params, src.as_posix()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
