"""Convert data/tuning.toml into build/gen/tuning.{h,c}.

Each `[table] key = int` becomes an int16_t field `table_key` of `tuning_t`. The ROM keeps a mutable
copy (`tuning`) so the debug menu can change values live; `tuning_reset()` restores the defaults.

Every param's comment starts with its allowed range, `key = 3  # [0..10] what it does`. The range is
validated here and written, with the doc text, to build/gen/tuning.lab.json so the feel lab can build
a slider for it (ADR 0008).
"""

import json

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from gbtools.errors import ConvertError

INT16_MIN, INT16_MAX = -32768, 32767
IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
TABLE_LINE = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")
PARAM_LINE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*[^#]*?(?:#(.*))?$")
RANGE = re.compile(r"^\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*(.*?)\s*$")


@dataclass
class Param:
    table: str
    key: str
    value: int
    min: int
    max: int
    doc: str

    @property
    def name(self) -> str:
        return f"{self.table}_{self.key}"


def parse(path: Path) -> list[tuple[str, int]]:
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConvertError(path, f"invalid TOML: {e}") from e

    fields: list[tuple[str, int]] = []
    for table, entries in doc.items():
        if not isinstance(entries, dict):
            raise ConvertError(path, f"'{table}' must be a [table] of integer params")
        if not IDENT.match(table):
            raise ConvertError(path, f"table name '{table}' must be lower_snake_case")
        for key, value in entries.items():
            where = f"{table}.{key}"
            if not IDENT.match(key):
                raise ConvertError(path, f"'{where}' must be lower_snake_case")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConvertError(path, f"'{where}' must be an integer (use 0/1 for switches)")
            if not INT16_MIN <= value <= INT16_MAX:
                raise ConvertError(path, f"'{where}' = {value} does not fit in int16")
            fields.append((f"{table}_{key}", value))
    return fields


def parse_params(path: Path) -> list[Param]:
    """`parse`, plus the `[min..max] doc` comment on each param's line. Raises ConvertError when a
    param has no range, the range is malformed, or the default lies outside it."""
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
        comment = comments[(table, key)]
        if comment is None or not (m := RANGE.match(comment)):
            raise ConvertError(
                path,
                f"'{where}' needs its allowed range at the start of its comment, e.g. "
                f"`{key} = {value}  # [0..10] what it does`; the feel lab builds its slider from it",
            )
        lo, hi, doc = int(m.group(1)), int(m.group(2)), m.group(3)
        if lo > hi:
            raise ConvertError(path, f"'{where}' has range [{lo}..{hi}]; the minimum must not exceed the maximum")
        if not lo <= value <= hi:
            raise ConvertError(
                path, f"'{where}' = {value} is outside its range [{lo}..{hi}]; change the value or widen the range"
            )
        params.append(Param(table, key, value, lo, hi, doc))
    return params


def lab_descriptor(params: list[Param], source: str) -> str:
    """The build/gen/tuning.lab.json text (ADR 0008). `tuning_t` is int16 fields in file order."""
    fields = [
        {
            "path": [p.table, p.key],
            "offset": 2 * i,
            "type": "i16",
            "default": p.value,
            "min": p.min,
            "max": p.max,
            "doc": p.doc,
        }
        for i, p in enumerate(params)
    ]
    head = json.dumps({"source": source, "symbol": "_tuning"})[:-1]
    return head + ', "fields": [\n  ' + ",\n  ".join(json.dumps(f) for f in fields) + "\n]}\n"


def render(fields: list[tuple[str, int]], source: str) -> tuple[str, str]:
    banner = f"/* Generated from {source} by tools/gbtools/tuning.py. Do not edit. */\n"
    members = "".join(f"    int16_t {name};\n" for name, _ in fields)
    header = (
        banner
        + "#ifndef GEN_TUNING_H\n#define GEN_TUNING_H\n\n#include <stdint.h>\n\n"
        + "typedef struct {\n" + members + "} tuning_t;\n\n"
        + "extern const tuning_t tuning_defaults;\n"
        + "extern tuning_t tuning;\n\n"
        + "void tuning_reset(void);\n\n#endif\n"
    )
    values = "".join(f"    {value}, /* {name} */\n" for name, value in fields)
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
        header, source_c = render([(p.name, p.value) for p in params], src.as_posix())
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
