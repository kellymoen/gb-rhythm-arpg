"""Asset resolution report and release gate (ADR 0007).

Claude-generated assets are named `<name>_genplaceholder.<ext>`; the author's `<name>.<ext>` replaces one
by existing. The Makefile resolves each name and passes the chosen files here:

    python -m gbtools.assets <list.txt> [--release] <resolved asset>...

Writes the resolved list to <list.txt> only when it changed (so outputs rebuild when the author adds a
file), prints a one-line report, and notes placeholders that the author's files have made unused.
With --release it fails if any placeholder would ship.
"""

import sys
from pathlib import Path

PLACEHOLDER = "_genplaceholder"
REPO = Path(__file__).resolve().parents[2]


def asset_name(path: Path) -> str:
    """`assets/ui/font_genplaceholder.png` and `assets/ui/font.png` are both the asset `font`."""
    stem = path.stem
    return stem[: -len(PLACEHOLDER)] if stem.endswith(PLACEHOLDER) else stem


def is_placeholder(path: Path) -> bool:
    return path.stem.endswith(PLACEHOLDER)


def unused_placeholders(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob(f"*{PLACEHOLDER}.*")
        if p.with_name(asset_name(p) + p.suffix).exists()
    )


def main(argv: list[str]) -> int:
    release = "--release" in argv
    args = [a for a in argv if a != "--release"]
    if not args:
        print("usage: python -m gbtools.assets <list.txt> [--release] <asset>...", file=sys.stderr)
        return 2
    out, files = Path(args[0]), [Path(a) for a in args[1:]]
    placeholders = [f for f in files if is_placeholder(f)]

    if release:
        if placeholders:
            print("release blocked: these assets are still Claude placeholders, not your work:", file=sys.stderr)
            for f in placeholders:
                print(f"  {f}  -> save your own as {f.with_name(asset_name(f) + f.suffix)}", file=sys.stderr)
            return 1
        return 0

    listing = "".join(f"{f}\n" for f in files)
    if not out.exists() or out.read_text() != listing:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(listing)

    mine = sorted(asset_name(f) for f in files if not is_placeholder(f))
    line = f"assets: yours {len(mine)}/{len(files)}"
    if mine:
        line += " (" + ", ".join(mine) + ")"
    print(line)
    for p in unused_placeholders(REPO / "assets"):
        print(f"  unused placeholder (your file replaces it; safe to delete): {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
