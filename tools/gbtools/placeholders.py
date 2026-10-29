"""Generate placeholder assets that follow the asset contract (ADR 0006), for the author to replace.

    python -m gbtools.placeholders [--force] {song,combat,sfx,font,hud,all}

Every file is written as `<name>_genplaceholder.<ext>` (ADR 0007); the author replaces it by saving
`<name>.<ext>` beside it. Never run by the build: it refuses to overwrite an existing placeholder
unless --force is given, and never writes one the author's file has already replaced.
"""

import argparse
import sys
from pathlib import Path

import mido
from PIL import Image

from gbtools.assets import PLACEHOLDER

REPO = Path(__file__).resolve().parents[2]
SHADES = [(232, 240, 216), (152, 184, 120), (72, 104, 72), (16, 32, 32)]

# Glyph order is part of the contract with src/gb/text.c.
FONT_CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-.:/!?%><"
FONT_5X7 = {
    " ": ["     "] * 7,
    "0": [" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "],
    "1": ["  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"],
    "3": ["#####", "   # ", "  #  ", "   # ", "    #", "#   #", " ### "],
    "4": ["   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "],
    "5": ["#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "],
    "6": ["  ## ", " #   ", "#    ", "#### ", "#   #", "#   #", " ### "],
    "7": ["#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "],
    "8": [" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "],
    "9": [" ### ", "#   #", "#   #", " ####", "    #", "   # ", " ##  "],
    "A": [" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "B": ["#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "],
    "C": [" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "],
    "D": ["#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"],
    "F": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "],
    "G": [" ### ", "#   #", "#    ", "# ###", "#   #", "#   #", " ####"],
    "H": ["#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "I": [" ### ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "],
    "J": ["  ###", "   # ", "   # ", "   # ", "   # ", "#  # ", " ##  "],
    "K": ["#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"],
    "N": ["#   #", "#   #", "##  #", "# # #", "#  ##", "#   #", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "P": ["#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"],
    "R": ["#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"],
    "S": [" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "V": ["#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "#   #", "# # #", "# # #", "# # #", " # # "],
    "X": ["#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"],
    "Y": ["#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "],
    "Z": ["#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"],
    "+": ["     ", "  #  ", "  #  ", "#####", "  #  ", "  #  ", "     "],
    "-": ["     ", "     ", "     ", "#####", "     ", "     ", "     "],
    ".": ["     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "],
    ":": ["     ", " ##  ", " ##  ", "     ", " ##  ", " ##  ", "     "],
    "/": ["     ", "    #", "   # ", "  #  ", " #   ", "#    ", "     "],
    "!": ["  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "],
    "?": [" ### ", "#   #", "    #", "   # ", "  #  ", "     ", "  #  "],
    "%": ["##   ", "##  #", "   # ", "  #  ", " #   ", "#  ##", "   ##"],
    ">": [" #   ", "  #  ", "   # ", "    #", "   # ", "  #  ", " #   "],
    "<": ["   # ", "  #  ", " #   ", "#    ", " #   ", "  #  ", "   # "],
}


def _indexed(w: int, h: int) -> Image.Image:
    img = Image.new("P", (w, h), 0)
    img.putpalette([c for rgb in SHADES for c in rgb])
    return img


def _write(name: str, force: bool, save) -> None:
    """`name` is the asset path without the suffix, e.g. "assets/ui/font.png"."""
    mine = REPO / name
    path = mine.with_name(mine.stem + PLACEHOLDER + mine.suffix)
    if mine.exists():
        print(f"skip {path.relative_to(REPO)} (replaced by your {mine.relative_to(REPO)})")
        return
    if path.exists() and not force:
        print(f"skip {path.relative_to(REPO)} (exists; use --force to overwrite)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path)
    print(f"wrote {path.relative_to(REPO)}")


def font(force: bool) -> None:
    """16 glyphs per row, 8x8 cells, ink = shade 3 on shade 0."""
    rows = -(-len(FONT_CHARS) // 16)
    img = _indexed(128, rows * 8)
    for i, ch in enumerate(FONT_CHARS):
        ox, oy = (i % 16) * 8 + 1, (i // 16) * 8
        for y, line in enumerate(FONT_5X7[ch]):
            for x, c in enumerate(line):
                if c == "#":
                    img.putpixel((ox + x, oy + y), 3)
    _write("assets/ui/font.png", force, img.save)


def hud(force: bool) -> None:
    """hud_bar.png: window tiles [bar, hit marker]. hud_sprites.png: 8x16 sprites [pip, downbeat pip]."""
    bar = _indexed(16, 8)
    for x in range(16):
        bar.putpixel((x, 0), 2)
        bar.putpixel((x, 7), 2)
    for x in range(8, 16):
        for y in range(1, 7):
            bar.putpixel((x, y), 1)
    for y in range(0, 8):
        bar.putpixel((11, y), 3)
        bar.putpixel((12, y), 3)
    _write("assets/ui/hud_bar.png", force, bar.save)

    spr = _indexed(16, 16)
    for (cx, r) in ((3, 1), (11, 3)):  # pip centre x and radius, both centred on row 3
        for y in range(8):
            for x in range(cx - 3, cx + 5):
                d = abs(x - cx) + abs(y - 3)
                if d <= r:
                    spr.putpixel((x, y), 3 if d < r else 2)
    _write("assets/ui/hud_sprites.png", force, spr.save)


def song(force: bool) -> None:
    """rhythmtest.mid: 128 BPM, 4/4, 8 bars, Am-F-C-G, every track type the converter understands."""
    ppq, bar = 480, 480 * 4
    eighth, sixteenth = ppq // 2, ppq // 4
    chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]  # Am F C G (root, 3rd, 5th)
    mid = mido.MidiFile(type=1, ticks_per_beat=ppq)

    def track(name: str, program: int | None, notes: list[tuple[int, int, int, int]]) -> None:
        t = mido.MidiTrack()
        t.append(mido.MetaMessage("track_name", name=name, time=0))
        msgs = []
        if program is not None:
            msgs.append((0, 0, mido.Message("program_change", program=program)))
        for start, length, note, vel in notes:
            msgs.append((start, 2, mido.Message("note_on", note=note, velocity=vel)))
            msgs.append((start + length, 1, mido.Message("note_off", note=note, velocity=0)))
        now = 0
        for at, _, msg in sorted(msgs, key=lambda m: (m[0], m[1])):
            t.append(msg.copy(time=at - now))
            now = at
        mid.tracks.append(t)

    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(128), time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(conductor)

    lead, stabs, bass, drums = [], [], [], []
    for b in range(8):
        root, third, fifth = chords[b // 2]
        start = b * bar
        arp = [root, third, fifth, root + 12, fifth + 12, root + 12, fifth, third]
        for i, n in enumerate(arp):
            lead.append((start + i * eighth, eighth - 30, n + 12, 110 if i % 2 == 0 else 80))
        for beat in range(4):
            stabs.append((start + beat * ppq + eighth, sixteenth, third + 12, 70))
            drums.append((start + beat * ppq, sixteenth, 36 if beat % 2 == 0 else 38, 120))
            hat = 46 if (b % 2 == 1 and beat == 3) else 42
            drums.append((start + beat * ppq + eighth, sixteenth, hat, 60))
        for beat in (0, 2):
            bass.append((start + beat * ppq, ppq * 2 - 40, root - 12, 120))

    track("P1", 0, lead)
    track("P2", 1, stabs)
    track("WAVE", 0, bass)
    track("NOISE", None, drums)
    track("HITS", 2, [(i * eighth, eighth, n, 100) for i, n in enumerate([69, 72, 74, 76, 79, 81])])
    _write("assets/music/rhythmtest.mid", force, lambda p: mid.save(p))


def _midi_track(mid, name: str, program: int | None, notes, ccs=()) -> None:
    """notes: (start, length, note, velocity); ccs: (tick, control, value). Ticks are absolute."""
    t = mido.MidiTrack()
    t.append(mido.MetaMessage("track_name", name=name, time=0))
    msgs = []
    if program is not None:
        msgs.append((0, 0, mido.Message("program_change", program=program)))
    for at, control, value in ccs:
        msgs.append((at, 0, mido.Message("control_change", control=control, value=value)))
    for start, length, note, vel in notes:
        msgs.append((start, 2, mido.Message("note_on", note=note, velocity=vel)))
        msgs.append((start + length, 1, mido.Message("note_off", note=note, velocity=0)))
    now = 0
    for at, _, msg in sorted(msgs, key=lambda m: (m[0], m[1])):
        t.append(msg.copy(time=at - now))
        now = at
    mid.tracks.append(t)


# Ascending A minor pentatonic: hit N of a combo string plays the N-th pitch, so any prefix of the
# set is a rising phrase that fits every chord of the combat loop (Am F G).
COMBAT_HITS = [69, 72, 74, 76, 79, 81, 84]  # A4 C5 D5 E5 G5 A5 C6


def combat(force: bool) -> None:
    """combat.mid: 8-bar A minor loop, 120 BPM changing to 140 at bar 5, every track the driver plays.

    Uses only the instrument programs and drum notes of instruments_genplaceholder.toml (pulse 0-2,
    wave 0, drums 36/38/42/46), so it still converts against your own instruments.toml if that keeps
    those programs."""
    ppq, bar = 480, 480 * 4
    eighth, sixteenth = ppq // 2, ppq // 4
    chords = [(57, 60, 64), (57, 60, 64), (53, 57, 60), (55, 59, 62)] * 2  # Am Am F G, twice
    mid = mido.MidiFile(type=1, ticks_per_beat=ppq)

    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(140), time=4 * bar))
    mid.tracks.append(conductor)

    lead, stabs, bass, drums = [], [], [], []
    for b, (root, third, fifth) in enumerate(chords):
        start = b * bar
        fast = b >= 4  # bars 5-8: the 140 BPM half pushes harder
        riff = [root, root, fifth, root, root + 12, fifth, third, fifth]
        for i, n in enumerate(riff):
            vel = 120 if i in (0, 3) else 85
            lead.append((start + i * eighth, eighth - 40, n + 12, vel))
        for beat in range(4):
            stabs.append((start + beat * ppq + eighth, sixteenth, third + 12, 75))
            if fast and beat == 3:
                stabs.append((start + beat * ppq + eighth + sixteenth, sixteenth - 20, fifth + 12, 60))
        for i in range(8):
            n = root - 12 + (12 if i == 6 else 0)
            bass.append((start + i * eighth, eighth - 30, n, 112 if i % 2 == 0 else 100))
        hits = {}  # tick -> (note, velocity); later entries replace earlier ones (one drum at a time)
        for beat in range(4):
            at = start + beat * ppq
            hats = 4 if fast else 2
            for h in range(1, hats):
                note = 46 if (b % 2 == 1 and beat == 3 and h == hats - 1) else 42
                hits[at + h * ppq // hats] = (note, 70 if h * 2 == hats else 45)
            hits[at] = (36 if beat % 2 == 0 else 38, 120)
        if fast:
            hits[start + ppq + eighth] = (36, 100)  # kick on the "and" of 2
        if b == 7:  # snare fill into the loop
            for i in range(1, 4):
                hits[start + 3 * ppq + i * sixteenth] = (38, 70 + 15 * i)
        drums += [(t, sixteenth // 2, n, v) for t, (n, v) in sorted(hits.items())]

    _midi_track(mid, "P1", 0, lead, ccs=[(4 * bar, 12, 40)])  # CC12: 25% duty for the 140 BPM half
    _midi_track(mid, "P2", 1, stabs)
    _midi_track(mid, "WAVE", 0, bass)
    _midi_track(mid, "NOISE", None, drums)
    _midi_track(mid, "HITS", 2, [(i * eighth, eighth, n, 100) for i, n in enumerate(COMBAT_HITS)])
    _write("assets/music/combat.mid", force, lambda p: mid.save(p))


# --- sound effects (format: docs/sfx.md) -------------------------------------------------------

SFX_HEADER = "# Placeholder sound effect (docs/sfx.md). Save your own as assets/sfx/{name}.toml to replace it.\n"

SFX = {
    "calib_click": """\
# A clean click for the latency calibration screen: a high square blip that the hardware length
# counter cuts after 16 ms, so its onset and length are exact.
channel = "P1"
priority = 12

[[step]]
frames = 2
volume = 15
duty = 2
pitch = "C7"
length = 4        # 4/256 s
""",
    "dodge": """\
# Dodge: a short rising "fwip". The P1 hardware sweep raises the pitch until it overflows and cuts.
channel = "P1"
priority = 6

[[step]]
frames = 8
volume = 10
env_pace = 1
duty = 1
pitch = "G3"
sweep_pace = 2
sweep_dir = "up"
sweep_step = 4
""",
    "hit": """\
# Light hit: a one-frame metallic snap (7-bit noise), then a quickly decaying crunch.
channel = "NOISE"
priority = 6

[[step]]
frames = 1
volume = 15
noise_shift = 1
noise_width = 7

[[step]]
frames = 6
volume = 13
env_pace = 1
noise_shift = 4
noise_width = 15
noise_divisor = 1
""",
    "hit_heavy": """\
# Heavy hit: a longer snap, then a crunch that drops into a low rumble as it decays.
channel = "NOISE"
priority = 7

[[step]]
frames = 2
volume = 15
noise_shift = 2
noise_width = 7

[[step]]
frames = 4
volume = 15
env_pace = 2
noise_shift = 5
noise_width = 15
noise_divisor = 1

[[step]]
frames = 10
noise_shift = 7   # no volume: changes the running noise without retriggering
""",
    "menu_move": """\
# Menu cursor: a soft, short blip.
channel = "P1"
priority = 3

[[step]]
frames = 4
volume = 7
env_pace = 1
duty = 2
pitch = "A5"
""",
    "menu_select": """\
# Menu confirm: two rising notes.
channel = "P1"
priority = 4

[[step]]
frames = 3
volume = 9
duty = 2
pitch = "E5"

[[step]]
frames = 9
volume = 9
env_pace = 1
pitch = "A5"
""",
    "perfect": """\
# Perfect dodge / slow-mo sting: a fast legato arpeggio (pitch changes without retriggering),
# then the top note rings out with a duty shimmer.
channel = "P1"
priority = 10

[[step]]
frames = 3
volume = 13
duty = 1
pitch = "E6"

[[step]]
frames = 3
pitch = "G6"

[[step]]
frames = 3
pitch = "B6"

[[step]]
frames = 4
pitch = "E7"

[[step]]
frames = 6
volume = 12
env_pace = 3
duty = 2
pitch = "E7"

[[step]]
frames = 6
duty = 1

[[step]]
frames = 12
duty = 2
""",
    "string_break": """\
# Combo string broke: a falling "bwow" on the wave channel with a square-ish shape. Volume drops in
# three steps (the wave channel has 100/50/25% only); 'slide' bends the period down every frame.
channel = "WAVE"
priority = 5
waves = ["FFFFFFFFFFFF00000000000000000000"]

[[step]]
frames = 4
volume = 15
pitch = "E3"
slide = -6

[[step]]
frames = 6
volume = 8
slide = -10

[[step]]
frames = 6
volume = 4
slide = -12
""",
    "swing_heavy": """\
# Heavy swing: a slower, darker whoosh that swells and then fades.
channel = "NOISE"
priority = 5

[[step]]
frames = 4
volume = 3
env_dir = "up"
env_pace = 1
noise_shift = 4
noise_divisor = 2

[[step]]
frames = 3
noise_shift = 5

[[step]]
frames = 10
volume = 10
env_pace = 2
noise_shift = 6
""",
    "swing_light": """\
# Light swing: a quick whoosh. The envelope swells up, the noise darkens, then it fades fast.
channel = "NOISE"
priority = 4

[[step]]
frames = 3
volume = 2
env_dir = "up"
env_pace = 1
noise_shift = 2
noise_divisor = 1

[[step]]
frames = 2
noise_shift = 3

[[step]]
frames = 5
volume = 7
env_pace = 1
noise_shift = 4
""",
}


def sfx(force: bool) -> None:
    """One register-level TOML per effect in assets/sfx/."""
    for name, body in SFX.items():
        text = SFX_HEADER.format(name=name) + body
        _write(f"assets/sfx/{name}.toml", force, lambda p, t=text: p.write_text(t))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbtools.placeholders")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("what", choices=["song", "combat", "sfx", "font", "hud", "all"])
    args = ap.parse_args(argv)
    for name, fn in (("song", song), ("combat", combat), ("sfx", sfx), ("font", font), ("hud", hud)):
        if args.what in (name, "all"):
            fn(args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
