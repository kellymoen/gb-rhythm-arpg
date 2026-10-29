"""Write edited values back into a table's source TOML, keeping its comments and layout (tomlkit)."""

import os
import tempfile
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError

from gbtools.errors import ConvertError

from .descriptor import Field


def _walk(doc, path: tuple, file: Path):
    """The container holding `path`'s last element, and that last key/index."""
    node = doc
    for step in path[:-1]:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError) as e:
            raise ConvertError(file, f"no [{'.'.join(map(str, path))}]: '{step}' not found; rebuild the descriptor") from e
    return node, path[-1]


def _present(node, key) -> bool:
    return key < len(node) if isinstance(key, int) else key in node


def save_values(file: Path, edits: list[tuple[Field, int]]) -> int:
    """Set each field's value in `file`. Returns how many values actually changed.

    Only edited values are rewritten (comments, blank lines and key order stay as they are), the
    trailing comment keeps its column when the value's width allows it, and the file is replaced
    atomically."""
    try:
        doc = tomlkit.parse(file.read_text())
    except (OSError, TOMLKitError) as e:
        raise ConvertError(file, f"cannot read for saving ({e})") from e
    changed = 0
    for f, value in edits:
        node, key = _walk(doc, f.path, file)
        new = f.toml_value(value)
        if f.absent and not _present(node, key):
            # A slot the TOML doesn't spell out yet (ADR 0008 "absent"): leave it out while it
            # still holds its default, otherwise add it, padding arrays with that default.
            if value == f.default:
                continue
            if isinstance(key, int):
                while len(node) < key:
                    node.append(f.toml_value(f.default))
                node.append(new)
            else:
                node[key] = new
            changed += 1
            continue
        try:
            old = node[key]
        except (KeyError, IndexError, TypeError) as e:
            raise ConvertError(file, f"'{f.label}' not found; the descriptor and the TOML disagree, rebuild") from e
        if old == new:
            continue
        trivia = node.item(key).trivia if hasattr(node, "item") else None
        old_width = len(str(old)) + len(trivia.comment_ws) if trivia and trivia.comment else None
        node[key] = new
        if old_width is not None:
            item = node.item(key) if hasattr(node, "item") else None
            if item is not None and item.trivia.comment:
                item.trivia.comment_ws = " " * max(1, old_width - len(str(new)))
        changed += 1
    if changed:
        fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=file.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as out:
                out.write(tomlkit.dumps(doc))
            os.replace(tmp, file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return changed
