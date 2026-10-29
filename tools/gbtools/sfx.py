"""Convert sound effects (assets/sfx/<name>.toml, register-level steps) into driver data (ADR 0006).

    python -m gbtools.sfx <out_dir> <effect.toml>...

The Makefile passes the resolved effects (ADR 0007): `hit_genplaceholder.toml` and `hit.toml` are
both the effect `hit`, id `SFX_HIT`. Ids are in name order.

Outputs in <out_dir>:
  sfx.h         SFX_<NAME> ids, SFX_COUNT and SFX_NAMES (include it as "sfx.h" from scenes)
  sfx_data.c    banked effect table; DEBUG builds keep a RAM copy (`sfx_table`) for the feel lab
  sfx.lab.json  lab descriptor for that RAM copy (ADR 0008)

Byte layout: src/audio/sfxdata.h. Author guide: docs/sfx.md.
"""

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from gbtools.assets import asset_name
from gbtools.errors import ConvertError

MAX_STEPS = 16
WAVES_MAX = 4
STEP_SIZE = 12
HEADER_SIZE = 4
EFFECT_SIZE = HEADER_SIZE + MAX_STEPS * STEP_SIZE
KEEP = 0xFF

CHANNELS = {"P1": 0, "P2": 1, "WAVE": 2, "NOISE": 3}
PULSE = ("P1", "P2")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
NOTE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

TOP_KEYS = {"channel", "priority", "waves", "step"}
# Keys a step may use on each channel. Trigger keys only take effect when the step sets `volume`.
STEP_KEYS = {
    "P1": ["frames", "volume", "env_dir", "env_pace", "length", "duty", "pitch", "slide",
           "sweep_pace", "sweep_dir", "sweep_step"],
    "P2": ["frames", "volume", "env_dir", "env_pace", "length", "duty", "pitch", "slide"],
    "WAVE": ["frames", "volume", "wave", "length", "pitch", "slide"],
    "NOISE": ["frames", "volume", "env_dir", "env_pace", "length", "noise_shift", "noise_width",
              "noise_divisor"],
}
TRIGGER_KEYS = {"env_dir", "env_pace", "length", "sweep_pace", "sweep_dir", "sweep_step", "wave"}
KEY_CHANNELS = {k: [c for c, keys in STEP_KEYS.items() if k in keys]
                for k in {k for keys in STEP_KEYS.values() for k in keys}}


@dataclass
class Effect:
    name: str
    source: str
    channel: str
    priority: int
    steps: list[bytes]
    waves: list[bytes]
    keys: list[set[str]]  # TOML keys present in each step (for the lab descriptor)


# --- parsing -----------------------------------------------------------------------------------


def note_period(path: Path, where: str, text: str, channel: str) -> int:
    m = NOTE.match(text)
    if not m:
        raise ConvertError(path, f"{where}: 'pitch' = {text!r} is not a note name; write e.g. \"A4\", "
                                 f"\"C#5\" or \"Bb3\", or a raw period 0-2047")
    letter, accidental, octave = m.groups()
    midi = (int(octave) + 1) * 12 + NOTE_INDEX[letter.upper()] + {"#": 1, "b": -1, "": 0}[accidental]
    hz = 440.0 * 2 ** ((midi - 69) / 12)
    clock = 65536 if channel == "WAVE" else 131072
    period = round(2048 - clock / hz)
    if not 0 <= period <= 2047:
        lowest = "C1" if channel == "WAVE" else "C2"
        raise ConvertError(path, f"{where}: note {text} is below the lowest {channel} pitch ({lowest})")
    return period


class _Step:
    def __init__(self, path: Path, where: str, entry: dict, channel: str):
        self.path, self.where, self.entry, self.channel = path, where, entry, channel

    def int(self, key, lo, hi, default=None):
        value = self.entry.get(key, default)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise ConvertError(self.path, f"{self.where}: '{key}' must be an integer {lo}-{hi}, got {value!r}")
        return value

    def choice(self, key, options: dict, default=None):
        value = self.entry.get(key, default)
        if value is None:
            return None
        if value not in options:
            names = " or ".join(f"{o!r}" if isinstance(o, int) else f'"{o}"' for o in options)
            raise ConvertError(self.path, f"{self.where}: '{key}' must be {names}, got {value!r}")
        return options[value]

    def pitch(self):
        value = self.entry.get("pitch")
        if value is None:
            return None
        if isinstance(value, str):
            return note_period(self.path, self.where, value, self.channel)
        return self.int("pitch", 0, 2047)


def _step_bytes(path: Path, channel: str, n: int, entry, first: bool, wave_count: int) -> bytes:
    where = f"step {n}"
    if not isinstance(entry, dict):
        raise ConvertError(path, f"{where}: write each step as a [[step]] table")
    allowed = STEP_KEYS[channel]
    for key in entry:
        if key not in allowed:
            if key in KEY_CHANNELS:
                raise ConvertError(path, f"{where}: '{key}' only applies to {' / '.join(KEY_CHANNELS[key])}; "
                                         f"this effect plays on {channel}, so remove it")
            raise ConvertError(path, f"{where}: unknown key '{key}' (keys for {channel}: {', '.join(allowed)})")
    s = _Step(path, where, entry, channel)
    trigger = "volume" in entry
    if not trigger:
        stray = sorted(TRIGGER_KEYS & entry.keys())
        if stray:
            raise ConvertError(path, f"{where}: '{stray[0]}' only takes effect when the step triggers the "
                                     f"channel; add 'volume' to this step or remove '{stray[0]}'")
        if first:
            raise ConvertError(path, f"{where}: the first step must set 'volume' (it starts the sound)")

    frames = s.int("frames", 1, 255, 1)
    volume = s.int("volume", 0, 15)
    out = [frames, KEEP if volume is None else volume, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    if channel != "WAVE":
        out[2] = s.choice("env_dir", {"down": 0, "up": 1}, "down" if trigger else None) or 0
        out[3] = s.int("env_pace", 0, 7, 0)
        out[4] = s.int("length", 1, 64) or 0
    else:
        out[4] = s.int("length", 1, 255) or 0
        wave = s.int("wave", 0, WAVES_MAX - 1, 0 if first else None)
        if wave is not None and wave >= wave_count:
            raise ConvertError(path, f"{where}: 'wave' = {wave} but the effect's 'waves' list has "
                                     f"{wave_count} shape(s); add a shape or pick 0-{wave_count - 1}")
        out[2] = KEEP if wave is None else wave

    if channel == "NOISE":
        out[5] = KEEP if (v := s.int("noise_shift", 0, 15, 0 if first else None)) is None else v
        out[6] = KEEP if (v := s.choice("noise_width", {15: 15, 7: 7}, 15 if first else None)) is None else v
        out[7] = KEEP if (v := s.int("noise_divisor", 0, 7, 0 if first else None)) is None else v
    else:
        if channel in PULSE:
            out[5] = KEEP if (v := s.int("duty", 0, 3, 2 if first else None)) is None else v
        period = s.pitch()
        if period is None and first:
            raise ConvertError(path, f"{where}: the first step must set 'pitch' (a note like \"A4\" or a "
                                     f"raw period 0-2047)")
        out[6], out[7] = (KEEP, KEEP) if period is None else (period & 0xFF, period >> 8)
        out[8] = s.int("slide", -128, 127, 0) & 0xFF

    if channel == "P1":
        out[9] = s.int("sweep_pace", 0, 7, 0)
        out[10] = s.choice("sweep_dir", {"up": 0, "down": 1}, "up")
        out[11] = s.int("sweep_step", 0, 7, 0)
    return bytes(out)


def load_effect(path: Path) -> Effect:
    name = asset_name(path)
    if not NAME.match(name):
        raise ConvertError(path, f"effect file name '{name}' must be lower_snake_case (it becomes SFX_<NAME>)")
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConvertError(path, f"invalid TOML: {e}") from e

    for key in doc:
        if key not in TOP_KEYS:
            raise ConvertError(path, f"unknown key '{key}' (top-level keys: channel, priority, waves, [[step]])")
    channel = doc.get("channel")
    if channel not in CHANNELS:
        raise ConvertError(path, f"'channel' must be \"P1\", \"P2\", \"WAVE\" or \"NOISE\", got {channel!r}")
    priority = doc.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 15:
        raise ConvertError(path, f"'priority' must be an integer 1-15 (higher steals from lower), got {priority!r}")

    waves: list[bytes] = []
    if "waves" in doc:
        if channel != "WAVE":
            raise ConvertError(path, f"'waves' only applies to WAVE effects; this one plays on {channel}")
        raw = doc["waves"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= WAVES_MAX:
            raise ConvertError(path, f"'waves' must be a list of 1-{WAVES_MAX} shapes")
        for i, w in enumerate(raw):
            if not isinstance(w, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", w):
                raise ConvertError(path, f"waves[{i}] must be exactly 32 hex digits (one 4-bit sample each)")
            waves.append(bytes.fromhex(w))
    elif channel == "WAVE":
        raise ConvertError(path, "WAVE effects need 'waves' = [\"<32 hex digits>\", ...] (the shapes steps play)")

    steps = doc.get("step")
    if not isinstance(steps, list) or not steps:
        raise ConvertError(path, "no steps; add at least one [[step]] table")
    if len(steps) > MAX_STEPS:
        raise ConvertError(path, f"{len(steps)} steps (max {MAX_STEPS}); use 'frames' to hold a step longer "
                                 f"or 'slide' for pitch sweeps")
    data = [_step_bytes(path, channel, n, e, n == 1, len(waves)) for n, e in enumerate(steps, 1)]
    return Effect(name, path.as_posix(), channel, priority, data, waves, [set(e) for e in steps])


def load_effects(paths: list[Path]) -> list[Effect]:
    effects = [load_effect(p) for p in paths]
    seen: dict[str, str] = {}
    for e in effects:
        if e.name in seen:
            raise ConvertError(Path(e.source), f"effect '{e.name}' is also defined by {seen[e.name]}; "
                                               f"keep one of the two files")
        seen[e.name] = e.source
    if len(effects) > 254:
        raise ConvertError(Path(effects[0].source).parent, "too many sound effects (max 254)")
    return sorted(effects, key=lambda e: e.name)


# --- output ------------------------------------------------------------------------------------

BANNER = "/* Generated by tools/gbtools/sfx.py from assets/sfx. Do not edit. */\n"


def wave_table(effects: list[Effect]) -> tuple[list[bytes], dict[str, int]]:
    """All effects' wave shapes in one table; returns it and each effect's base index."""
    table: list[bytes] = []
    base: dict[str, int] = {}
    for e in effects:
        base[e.name] = len(table)
        table += e.waves
    return table, base


def effect_bytes(e: Effect, wave_base: int) -> bytes:
    """The sfx_t record exactly as it sits in memory (for tests and the lab)."""
    head = bytes([CHANNELS[e.channel], e.priority, len(e.steps), wave_base])
    body = b"".join(e.steps) + bytes(STEP_SIZE * (MAX_STEPS - len(e.steps)))
    return head + body


def _hex(data: bytes) -> str:
    return ", ".join(f"0x{b:02X}" for b in data)


def _step_c(step: bytes) -> str:
    """Step initialiser; `slide` (byte 8) is an int8_t, so it is written signed."""
    return ", ".join(str(b - 256 if b > 127 else b) if i == 8 else f"0x{b:02X}" for i, b in enumerate(step))


def render_header(effects: list[Effect]) -> str:
    ids = "".join(f"#define SFX_{e.name.upper()} {i}\n" for i, e in enumerate(effects))
    names = ", ".join(f'"{e.name.upper().replace("_", " ")}"' for e in effects) or '""'
    return (BANNER + "#ifndef GEN_SFX_H\n#define GEN_SFX_H\n\n#include \"audio/sfx.h\"\n\n" + ids
            + f"#define SFX_COUNT {len(effects)}\n\n"
            + "/* Display names, for audition screens: static const char *const n[] = SFX_NAMES; */\n"
            + f"#define SFX_NAMES {{ {names} }}\n\n#endif\n")


def render_c(effects: list[Effect]) -> str:
    waves, base = wave_table(effects)
    n = max(len(effects), 1)
    recs = []
    for e in effects:
        steps = "".join(f"        {{ {_step_c(s)} }},\n" for s in e.steps)
        recs.append(f"    {{ {CHANNELS[e.channel]}, {e.priority}, {len(e.steps)}, {base[e.name]}, "
                    f"{{ /* {e.name}: {e.channel} */\n{steps}    }} }},\n")
    recs_c = "".join(recs) or "    { 0 },\n"
    wave_c = "".join(f"    {{ {_hex(w)} }},\n" for w in waves) or "    { 0 },\n"
    index = ", ".join(f"&SFX_SRC[{i}]" for i in range(len(effects))) or "0"
    return (BANNER + "#pragma bank 255\n\n#include <gbdk/platform.h>\n#include <string.h>\n\n"
            + '#include "audio/sfxdata.h"\n\nBANKREF(sfx_data)\n\n'
            + f"const uint8_t sfx_count = {len(effects)};\n\n"
            + f"const sfx_t sfx_defaults[{n}] = {{\n{recs_c}}};\n\n"
            + f"const uint8_t sfx_waves[][16] = {{\n{wave_c}}};\n\n"
            + "#ifdef DEBUG\n"
            + f"sfx_t sfx_table[{n}];\n#define SFX_SRC sfx_table\n\n"
            + "void sfx_reset(void) BANKED\n{\n    memcpy(sfx_table, sfx_defaults, sizeof sfx_defaults);\n}\n"
            + "#else\n#define SFX_SRC sfx_defaults\n#endif\n\n"
            + f"const sfx_t *const sfx_index[{n}] = {{ {index} }};\n")


# Lab descriptor: (key, byte offset in the step, type, min, max, doc, extra) per channel.
_DIR = {"type": "enum", "values": {"down": 0, "up": 1}}
_COMMON = [
    ("frames", 0, "u8", 1, 255, "frames this step lasts", {}),
    ("volume", 1, "u8", 0, 15, "0-15; set = trigger a new note, absent = change the running sound",
     {"none": KEEP}),
]
_ENV = [
    ("env_dir", 2, "enum", None, None, "trigger: envelope direction", _DIR),
    ("env_pace", 3, "u8", 0, 7, "trigger: envelope speed, 0 = hold, 1 fastest", {}),
]
_PITCH = [
    ("pitch", 6, "u16", 0, 2047, "period (TOML may also hold a note name; the lab saves a number)",
     {"none": 0xFFFF}),
    ("slide", 8, "i8", -128, 127, "period added each frame after the step's first", {}),
]
LAB_FIELDS = {
    "P1": _COMMON + _ENV + [("length", 4, "u8", 0, 64, "trigger: hardware cut in 1/256 s, 0 = off", {}),
                            ("duty", 5, "u8", 0, 3, "0 = 12.5%, 1 = 25%, 2 = 50%, 3 = 75%", {"none": KEEP})]
    + _PITCH + [("sweep_pace", 9, "u8", 0, 7, "trigger: NR10 sweep pace, 0 = off", {}),
                ("sweep_dir", 10, "enum", None, None, "trigger: sweep direction",
                 {"type": "enum", "values": {"up": 0, "down": 1}}),
                ("sweep_step", 11, "u8", 0, 7, "trigger: NR10 sweep step", {})],
    "P2": _COMMON + _ENV + [("length", 4, "u8", 0, 64, "trigger: hardware cut in 1/256 s, 0 = off", {}),
                            ("duty", 5, "u8", 0, 3, "0 = 12.5%, 1 = 25%, 2 = 50%, 3 = 75%", {"none": KEEP})]
    + _PITCH,
    "WAVE": _COMMON + [("wave", 2, "u8", 0, WAVES_MAX - 1, "trigger: index into 'waves'", {"none": KEEP}),
                       ("length", 4, "u8", 0, 255, "trigger: hardware cut in 1/256 s, 0 = off", {})] + _PITCH,
    "NOISE": _COMMON + _ENV + [
        ("length", 4, "u8", 0, 64, "trigger: hardware cut in 1/256 s, 0 = off", {}),
        ("noise_shift", 5, "u8", 0, 15, "NR43 clock shift, higher = lower", {"none": KEEP}),
        ("noise_width", 6, "u8", 7, 15, "7 = metallic, 15 = noisy", {"none": KEEP, "step": 8}),
        ("noise_divisor", 7, "u8", 0, 7, "NR43 divisor", {"none": KEEP}),
    ],
}


def render_lab(effects: list[Effect]) -> str:
    fields = []
    for i, e in enumerate(effects):
        base = i * EFFECT_SIZE
        fields.append({"source": e.source, "path": ["priority"], "offset": base + 1, "type": "u8",
                       "default": e.priority, "min": 1, "max": 15,
                       "doc": f"{e.name}: steals {e.channel} from equal or lower priority"})
        fields.append({"source": e.source, "path": ["step"], "offset": base + 2, "type": "u8",
                       "default": len(e.steps), "min": 1, "max": MAX_STEPS, "array_length": True,
                       "doc": f"{e.name}: steps played (slots past the file's [[step]] tables are new steps)"})
        for n, (data, keys) in enumerate(zip(e.steps, e.keys)):
            trigger = data[1] != KEEP
            for key, off, typ, lo, hi, doc, extra in LAB_FIELDS[e.channel]:
                if key in TRIGGER_KEYS and not trigger:
                    continue
                at = base + HEADER_SIZE + n * STEP_SIZE + off
                if typ == "u16":
                    value = data[off] | data[off + 1] << 8
                elif typ == "i8":
                    value = data[off] - 256 if data[off] > 127 else data[off]
                else:
                    value = data[off]
                f = {"source": e.source, "path": ["step", n, key], "offset": at, "type": typ,
                     "default": value, "doc": doc}
                if lo is not None:
                    f["min"], f["max"] = lo, hi
                f.update({k: v for k, v in extra.items() if k != "type"})
                fields.append(f)
    return json.dumps({
        "source": "assets/sfx",
        "symbol": "_sfx_table",
        "layout": {"effect_size": EFFECT_SIZE, "header_size": HEADER_SIZE, "step_size": STEP_SIZE,
                   "max_steps": MAX_STEPS},
        "fields": fields,
    }, indent=1) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m gbtools.sfx <out_dir> <effect.toml>...", file=sys.stderr)
        return 2
    out_dir = Path(argv[0])
    try:
        effects = load_effects([Path(p) for p in argv[1:]])
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sfx.h").write_text(render_header(effects))
    (out_dir / "sfx_data.c").write_text(render_c(effects))
    (out_dir / "sfx.lab.json").write_text(render_lab(effects))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
