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


def _strip(file: Path, e: ConvertError) -> str:
    """A converter's message without its leading `<path>: `."""
    text = str(e.args[0])
    return text.split(": ", 1)[1] if ": " in text else text


def _resize(doc, f: Field, length: int, file: Path) -> None:
    """Make the array of tables at `f.path` hold `length` tables: append empty ones, or drop the tail."""
    node, key = _walk(doc, f.path, file)
    try:
        arr = node[key]
    except (KeyError, IndexError, TypeError) as e:
        raise ConvertError(file, f"'{f.label}' (the step count) not found; rebuild the descriptor") from e
    while len(arr) < length:
        arr.append(tomlkit.table())
    while len(arr) > length:
        del arr[len(arr) - 1]


def save_values(file: Path, edits: list[tuple[Field, int]], validate=None) -> int:
    """Set each field's value in `file`. Returns how many values actually changed.

    Only edited values are rewritten (comments, blank lines and key order stay as they are), the
    trailing comment keeps its column when the value's width allows it, and the file is replaced
    atomically. ADR 0008 defines the field flags this honours:

    - a key the TOML leaves out (`absent` slots, implicit converter defaults): it is added only once its
      value differs from the field's default. A missing *parent* table is an error (stale descriptor).
    - `none`: the key is deleted when the value is the sentinel, and added when a real value is set
      where it was missing.
    - `array_length`: resizes the array of tables (appending empty ones, or dropping the tail), and
      edits to elements past the new length are ignored.
    - enum fields are written by name; a numeric value replaces a string (a pitch note name).

    `validate(path)` may raise ConvertError for a candidate file; then nothing is written and the
    error is re-raised against `file`."""
    try:
        doc = tomlkit.parse(file.read_text())
    except (OSError, TOMLKitError) as e:
        raise ConvertError(file, f"cannot read for saving ({e})") from e
    changed = 0
    lengths: dict[tuple, int] = {}
    for f, value in edits:
        if f.array_length:
            node, key = _walk(doc, f.path, file)
            before = len(node[key]) if _present(node, key) else None
            _resize(doc, f, value, file)
            lengths[f.path] = value
            changed += before != value
    for f, value in edits:
        if f.array_length:
            continue
        if any(f.path[: len(p)] == p and len(f.path) > len(p) and isinstance(f.path[len(p)], int)
               and f.path[len(p)] >= n for p, n in lengths.items()):
            continue  # an element the author dropped by lowering the count
        try:
            node, key = _walk(doc, f.path, file)
        except ConvertError:
            if f.absent and value == f.default:
                continue
            if not any(isinstance(p, int) for p in f.path[:-1]):
                raise
            raise ConvertError(
                file, f"'{f.label}' is in an element the file does not have; raise the count that covers it "
                      f"(its array_length field) so the lab can add it") from None
        missing = not _present(node, key)
        if f.none is not None and value == f.none:
            if not missing:
                del node[key]
                changed += 1
            continue
        if missing:
            # A key the file leaves out (the converter's implicit default, a slot past an array's end,
            # an unset `none`): nothing to write while the value is still that default, else add it.
            if value == f.default:
                continue
            new = f.toml_value(value)
            if isinstance(key, int):
                # A slot the TOML doesn't spell out yet (ADR 0008 "absent"): pad arrays with the default.
                while len(node) < key:
                    node.append(f.toml_value(f.default))
                node.append(new)
            else:
                node[key] = new
            changed += 1
            continue
        old, new = node[key], f.toml_value(value)
        if old == new:
            continue
        trivia = node.item(key).trivia if hasattr(node, "item") else None
        old_width = len(node.item(key).as_string().strip()) + len(trivia.comment_ws) if trivia and trivia.comment else None
        node[key] = new
        if old_width is not None:
            item = node.item(key) if hasattr(node, "item") else None
            if item is not None and item.trivia.comment:
                item.trivia.comment_ws = " " * max(1, old_width - len(item.as_string().strip()))
        changed += 1
    if changed:
        text = tomlkit.dumps(doc)
        if validate:
            check_dir = Path(tempfile.mkdtemp(dir=file.parent, prefix=".lab-check-"))
            try:
                candidate = check_dir / file.name
                candidate.write_text(text)
                validate(candidate)
            except ConvertError as e:
                raise ConvertError(file, f"not saved, the converter would reject it: {_strip(candidate, e)}") from e
            finally:
                for p in check_dir.iterdir():
                    p.unlink()
                check_dir.rmdir()
        fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=file.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as out:
                out.write(text)
            os.replace(tmp, file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return changed
