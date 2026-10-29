"""Lab descriptor fields (ADR 0008), built one way for every converter that writes a `.lab.json`.

`field()` returns one entry of a descriptor's `fields` list with its keys in a fixed order, leaving out
optional keys that are unset. It checks the converter's own call (a type the lab doesn't know, an enum
without values, a numeric field without a range), not the author's data, so mistakes raise ValueError.
The reading side is tools/lab/descriptor.py.
"""

TYPES = ("i8", "u8", "i16", "u16", "enum")


def field(
    path: list,
    offset: int,
    type: str,
    default: int | str,
    doc: str,
    *,
    min: int | None = None,
    max: int | None = None,
    values: dict[str, int] | None = None,
    source: str | None = None,
    step: int | None = None,
    none: int | None = None,
    absent: bool = False,
    array_length: bool = False,
    restart: bool = False,
) -> dict:
    if type not in TYPES:
        raise ValueError(f"{path}: type {type!r} is not one of {', '.join(TYPES)}")
    if type == "enum":
        if values is None or min is not None or max is not None:
            raise ValueError(f"{path}: an enum field takes `values` and no min/max")
        if none is not None:
            raise ValueError(f"{path}: an enum field puts its unset sentinel in `values`, not `none`")
    elif min is None or max is None or values is not None:
        raise ValueError(f"{path}: a {type} field takes min and max, and no `values`")

    out: dict = {}
    if source is not None:
        out["source"] = source
    out |= {"path": list(path), "offset": offset, "type": type}
    if values is not None:
        out["values"] = values
    out["default"] = default
    if min is not None:
        out["min"], out["max"] = min, max
    for key, value in (("step", step), ("none", none)):
        if value is not None:
            out[key] = value
    out["doc"] = doc
    for key, flag in (("absent", absent), ("array_length", array_length), ("restart", restart)):
        if flag:
            out[key] = True
    return out
