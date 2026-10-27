"""Convert data/tuning.toml into build/gen/tuning.{h,c}.

Each `[table] key = int` becomes an int16_t field `table_key` of `tuning_t`. The ROM keeps a mutable
copy (`tuning`) so the debug menu can change values live; `tuning_reset()` restores the defaults.
"""

import re
import sys
import tomllib
from pathlib import Path

from gbtools.errors import ConvertError

INT16_MIN, INT16_MAX = -32768, 32767
IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


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
        header, source_c = render(parse(src), src.as_posix())
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tuning.h").write_text(header)
    (out_dir / "tuning.c").write_text(source_c)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
