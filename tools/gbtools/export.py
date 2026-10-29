"""Export Aseprite sources to sheet PNG + JSON that the converters read (ADR 0006, 0007).

    python -m gbtools.export [--aseprite PATH] [--force] <out_dir> <file.aseprite>...

For each source writes <out_dir>/<stem>.png (all frames in one row), <stem>.json (frames, durations,
tags with user data, slices) and <stem>.sha1 (hash of the source). Exports are committed, because CI
has no Aseprite:

* With Aseprite available the export is redone whenever the source's hash differs from <stem>.sha1.
* Without it the committed export is used, but only if its hash matches the source; otherwise the
  build fails and says what to do.
"""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from gbtools.errors import ConvertError

STALE_FIX = "run make with Aseprite installed and commit exports/"


def source_hash(source: Path) -> str:
    return hashlib.sha1(source.read_bytes()).hexdigest()


def export_paths(source: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    return out_dir / f"{source.stem}.png", out_dir / f"{source.stem}.json", out_dir / f"{source.stem}.sha1"


def is_fresh(source: Path, out_dir: Path) -> tuple[bool, str]:
    """(fresh, reason) for the committed export of `source`."""
    png, js, sha = export_paths(source, out_dir)
    missing = [p.name for p in (png, js, sha) if not p.exists()]
    if missing:
        return False, f"has no export ({', '.join(missing)} missing in {out_dir})"
    if sha.read_text().strip() != source_hash(source):
        return False, f"changed since {png.name} was exported (hash differs from {sha.name})"
    return True, ""


def aseprite_available(aseprite: str | None) -> bool:
    return bool(aseprite) and os.path.isfile(aseprite) and os.access(aseprite, os.X_OK)


def run_aseprite(aseprite: str, source: Path, out_dir: Path) -> None:
    png, js, sha = export_paths(source, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [aseprite, "-b", str(source), "--sheet", str(png), "--sheet-type", "horizontal",
           "--data", str(js), "--format", "json-array", "--list-tags", "--list-slices"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConvertError(source, f"could not run Aseprite ({aseprite}): {e}; point ASEPRITE at the Aseprite "
                                   f"executable, e.g. make ASEPRITE=/path/to/aseprite") from e
    if done.returncode != 0 or not png.exists() or not js.exists():
        raise ConvertError(source, f"Aseprite export failed (exit {done.returncode}): "
                                   f"{(done.stderr or done.stdout).strip()}; open the file in Aseprite, fix what "
                                   f"it reports and save it, then run make again")
    sha.write_text(source_hash(source) + "\n")


def export(source: Path, out_dir: Path, aseprite: str | None, force: bool = False) -> str:
    """Make sure out_dir holds a fresh export of `source`. Returns "exported" or "up to date"."""
    if not source.is_file():
        raise ConvertError(source, "does not exist; check the path, or run `make placeholders` to recreate a "
                                   "missing placeholder (the Makefile passes assets/sprites/<name>[_genplaceholder]"
                                   ".aseprite)")
    fresh, reason = is_fresh(source, out_dir)
    if fresh and not force:
        for p in export_paths(source, out_dir):
            p.touch()  # so make sees the outputs as newer than the source
        return "up to date"
    if not aseprite_available(aseprite):
        raise ConvertError(source, f"{reason or 'export forced'} and Aseprite was not found "
                                   f"(ASEPRITE={aseprite or ''}); {STALE_FIX}")
    run_aseprite(aseprite, source, out_dir)
    return "exported"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbtools.export")
    ap.add_argument("--aseprite", default=None, help="path to the Aseprite executable")
    ap.add_argument("--force", action="store_true", help="re-export even if the hash matches")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("sources", nargs="+", type=Path)
    args = ap.parse_args(argv)
    status = 0
    for source in args.sources:
        try:
            result = export(source, args.out_dir, args.aseprite, args.force)
        except ConvertError as e:
            print(e, file=sys.stderr)
            status = 1
            continue
        if result == "exported":
            print(f"exported {source} -> {args.out_dir}/{source.stem}.png, .json")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
