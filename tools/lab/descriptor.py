"""Lab descriptors (ADR 0008): `build/gen/<table>.lab.json`, one per tunable RAM table.

A descriptor names the table's source TOML, its RAM symbol and its fields. Each field has a key `path`
into the TOML (ints index arrays of tables), a byte `offset` into the table, a `type`, `default`, `min`,
`max` and `doc`, and optionally enum `values` and `restart`. This module loads and validates them and
converts values to and from the little-endian bytes the ROM keeps in WRAM. Nothing here is specific to
tuning.toml: combo patterns, sound and enemy tables use the same format.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from gbtools.errors import ConvertError

# type -> (size in bytes, signed)
TYPES = {"i8": (1, True), "u8": (1, False), "i16": (2, True), "u16": (2, False), "enum": (1, False)}


@dataclass
class Field:
    id: str
    path: tuple  # str keys and int indices into the source TOML
    offset: int
    type: str
    default: int
    min: int
    max: int
    doc: str = ""
    values: dict[str, int] | None = None
    restart: bool = False
    absent: bool = False  # not in the TOML yet (e.g. a step past a string's end); saving adds it

    @property
    def size(self) -> int:
        return TYPES[self.type][0]

    @property
    def signed(self) -> bool:
        return TYPES[self.type][1]

    @property
    def label(self) -> str:
        return ".".join(str(p) for p in self.path)

    def encode(self, value: int) -> bytes:
        """Little-endian bytes for `value`; ValueError (naming the field) if it is out of range."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{self.label}: {value!r} is not an integer")
        if not self.min <= value <= self.max:
            raise ValueError(f"{self.label}: {value} is outside its range [{self.min}..{self.max}]")
        if self.values is not None and value not in self.values.values():
            raise ValueError(f"{self.label}: {value} is not one of {self.values}")
        return value.to_bytes(self.size, "little", signed=self.signed)

    def decode(self, raw: bytes) -> int:
        return int.from_bytes(bytes(raw), "little", signed=self.signed)

    def toml_value(self, value: int):
        """What to write into the TOML for `value`: the enum name when the source uses names."""
        if self.values is not None:
            for name, v in self.values.items():
                if v == value:
                    return name
        return value


@dataclass
class Table:
    name: str  # file stem without ".lab", e.g. "tuning"
    file: Path  # the .lab.json
    source: str  # TOML path relative to the repo root
    symbol: str
    fields: list[Field] = field(default_factory=list)

    def find(self, path: tuple) -> Field | None:
        return next((f for f in self.fields if f.path == path), None)


def _fail(file: Path, where: str, message: str):
    raise ConvertError(file, f"{where}: {message}")


def load_table(file: Path) -> Table:
    try:
        doc = json.loads(file.read_text())
    except json.JSONDecodeError as e:
        raise ConvertError(file, f"invalid JSON ({e}); regenerate it with `make DEBUG=1`") from e
    if not isinstance(doc, dict):
        _fail(file, "descriptor", "must be a JSON object with 'source', 'symbol' and 'fields'")
    for key in ("source", "symbol", "fields"):
        if key not in doc:
            _fail(file, "descriptor", f"missing '{key}'; the converter that wrote it must emit it (ADR 0008)")
    name = file.name.removesuffix(".lab.json")
    table = Table(name, file, doc["source"], doc["symbol"])
    seen: set[tuple] = set()
    for i, raw in enumerate(doc["fields"]):
        where = f"fields[{i}]"
        if not isinstance(raw, dict):
            _fail(file, where, "must be an object")
        required = ("path", "offset", "type", "default") + (() if raw.get("type") == "enum" else ("min", "max"))
        for key in required:
            if key not in raw:
                _fail(file, where, f"missing '{key}'")
        path = tuple(raw["path"])
        where = f"field {'.'.join(map(str, path))}"
        if not path or not all(isinstance(p, (str, int)) and not isinstance(p, bool) for p in path):
            _fail(file, where, "'path' must be a non-empty list of TOML keys and array indices")
        if path in seen:
            _fail(file, where, "appears twice; every field needs a unique path")
        seen.add(path)
        ftype = raw["type"]
        if ftype not in TYPES:
            _fail(file, where, f"type '{ftype}' must be one of {', '.join(TYPES)}")
        values = raw.get("values")
        if ftype == "enum":
            if not isinstance(values, dict) or not values or not all(isinstance(v, int) for v in values.values()):
                _fail(file, where, "enum fields need a non-empty 'values' object mapping names to integers")
        elif values is not None:
            _fail(file, where, "'values' is only valid on enum fields")
        default = raw["default"]
        if isinstance(default, str) and values and default in values:
            default = values[default]
        f = Field(
            id=f"{table.name}:{'.'.join(map(str, path))}",
            path=path,
            offset=raw["offset"],
            type=ftype,
            default=default,
            min=raw.get("min", min(values.values()) if ftype == "enum" else None),
            max=raw.get("max", max(values.values()) if ftype == "enum" else None),
            doc=raw.get("doc", ""),
            values=values,
            restart=bool(raw.get("restart", False)),
            absent=bool(raw.get("absent", False)),
        )
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (f.offset, f.default, f.min, f.max)):
            _fail(file, where, "'offset', 'default', 'min' and 'max' must be integers")
        if f.offset < 0:
            _fail(file, where, "'offset' must not be negative")
        lo = -(1 << (8 * f.size - 1)) if f.signed else 0
        hi = (1 << (8 * f.size - 1)) - 1 if f.signed else (1 << (8 * f.size)) - 1
        if f.min > f.max or f.min < lo or f.max > hi:
            _fail(file, where, f"range [{f.min}..{f.max}] must satisfy min <= max and fit in {f.type} [{lo}..{hi}]")
        if not f.min <= f.default <= f.max:
            _fail(file, where, f"default {f.default} is outside its range [{f.min}..{f.max}]")
        table.fields.append(f)
    return table


def load_tables(gen_dir: Path) -> list[Table]:
    """Every `*.lab.json` in `gen_dir`, tuning first, then alphabetical."""
    files = sorted(gen_dir.glob("*.lab.json"), key=lambda p: (p.name != "tuning.lab.json", p.name))
    return [load_table(p) for p in files]
