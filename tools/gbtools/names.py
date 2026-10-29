"""Naming rules shared by the converters: C-safe identifiers and on-screen labels.

IDENT is the lower_snake_case rule for anything that becomes a C name (`SFX_<NAME>`, `COMBO_STRING_<NAME>`,
a song, a sprite, a `tuning_t` field). Labels are text the ROM prints with the BG font (src/gb/text.h),
so they may only use its glyphs.
"""

import re

IDENT = re.compile(r"^[a-z][a-z0-9_]*$")

# The BG font's glyphs, in order (contract with src/gb/text.h and tools/gbtools/placeholders.py).
FONT_GLYPHS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-.:/!?%><"


def is_ident(name: object) -> bool:
    return isinstance(name, str) and bool(IDENT.match(name))


def display_name(name: str) -> str:
    """`crush_lunge` -> `CRUSH LUNGE`: the default on-screen label of an identifier."""
    return name.upper().replace("_", " ")


def short_label(name: str, width: int) -> str:
    """`display_name`, shortened to `width` columns by trimming the longest word (the last of equals)
    one letter at a time: `perfect_window` at 10 -> `PERFE WIND`. Keeps every word's first letter."""
    words = display_name(name).split(" ")
    while len(" ".join(words)) > width:
        i = max(range(len(words)), key=lambda k: (len(words[k]), k))
        if len(words[i]) == 1:  # every word is one letter: drop the last
            words.pop()
        else:
            words[i] = words[i][:-1]
    return " ".join(words)


def label_problem(label: object, width: int) -> str | None:
    """Why `label` cannot be printed in `width` columns with the BG font, or None if it can."""
    if not isinstance(label, str) or not label.strip():
        return "must be a non-empty string"
    if len(label) > width:
        return f"is {len(label)} characters; at most {width} fit"
    bad = sorted({c for c in label if c not in FONT_GLYPHS})
    if bad:
        return (f"uses {', '.join(repr(c) for c in bad)}, which the font has no glyph for; use only "
                f"A-Z, 0-9, space and {FONT_GLYPHS[37:]}")
    return None
