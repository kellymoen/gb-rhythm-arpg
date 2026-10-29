"""Symbol lookup in the SDCC/GBDK `.noi` file written next to the ROM by `make DEBUG=1`."""

from pathlib import Path

from gbtools.errors import ConvertError


def load_symbols(rom: Path) -> dict[str, int]:
    noi = rom.with_suffix(".noi")
    if not noi.exists():
        raise ConvertError(noi, f"missing; build the DEBUG ROM first (`make DEBUG=1`) so {rom.name} has symbols")
    out = {}
    for line in noi.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "DEF":
            out[parts[1]] = int(parts[2], 16)
    return out
