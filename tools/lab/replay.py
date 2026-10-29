"""Replay files: recorded input that reproduces a play session frame for frame.

A replay is deterministic because the Game Boy is: boot the ROM with blank cartridge RAM, hold the
same buttons on the same frames, poke the same tuning values on the same frames, and the machine ends
in the same state. The file also stores what the ROM judged (`expect`), so a replay doubles as a
regression test: `python -m lab replay <file> --check` replays headless and fails on any difference.
The format is documented in docs/lab.md ("Replay file format").

Frame numbering: the ROM first runs `warmup_frames` ticks untouched (PyBoy's boot animation, then the ROM's
own init, which resets the tuning tables), so frame 0 is the main menu. Frame `f` is then the (0-based)
f-th call to `PyBoy.tick()` after that warm-up. Inputs and pokes
listed at `f` take effect before that tick runs. A press the ROM judges during tick `f` is `f` in
`expect.presses`.
"""

import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gbtools.errors import ConvertError

from .descriptor import TYPES

FORMAT = "beatarpg-replay"
VERSION = 1

# GBDK joypad masks, as reported in the press log.
BUTTONS = {"right": 0x01, "left": 0x02, "up": 0x04, "down": 0x08, "a": 0x10, "b": 0x20, "select": 0x40, "start": 0x80}
GRADES = ["OFFBEAT", "GOOD", "PERFECT"]  # grade_t order in the ROM
WARMUP = 120  # ticks before frame 0: the boot animation (~65) plus the ROM's init; same as tests/rom
BLANK_SRAM = bytes(16 * 8 * 1024)  # every cartridge RAM bank, zeroed: replays never load a stale .ram


def mask_to_names(mask: int) -> list[str]:
    return [n for n, bit in BUTTONS.items() if mask & bit]


def names_to_mask(names) -> int:
    return sum(BUTTONS[n] for n in names)


@dataclass(frozen=True)
class Press:
    f: int
    buttons: int  # GBDK mask
    grade: int  # index into GRADES
    frames: int  # signed frame error: < 0 early, > 0 late

    def to_json(self) -> dict:
        return {"f": self.f, "buttons": mask_to_names(self.buttons), "grade": GRADES[self.grade], "frames": self.frames}

    def __str__(self) -> str:
        return f"f{self.f} {'+'.join(mask_to_names(self.buttons))} {GRADES[self.grade]} {self.frames:+d}"


@dataclass(frozen=True)
class Poke:
    f: int
    symbol: str
    offset: int
    type: str
    value: int
    path: tuple = ()  # advisory: where the value lives in the source TOML

    def to_json(self) -> dict:
        d = {"f": self.f, "symbol": self.symbol, "offset": self.offset, "type": self.type, "value": self.value}
        if self.path:
            d["path"] = list(self.path)
        return d

    def encode(self) -> bytes:
        size, signed = TYPES[self.type]
        return self.value.to_bytes(size, "little", signed=signed)


@dataclass
class Replay:
    frames: int
    inputs: list[tuple[int, frozenset]] = field(default_factory=list)  # (frame, buttons held from then on)
    pokes: list[Poke] = field(default_factory=list)
    model: str = "cgb"
    rom_name: str = ""
    rom_sha1: str = ""
    expect_presses: list[Press] | None = None
    expect_screen_sha1: str | None = None
    created: str = ""
    notes: str = ""
    warmup: int = WARMUP

    def to_json(self) -> dict:
        expect = {}
        if self.expect_presses is not None:
            expect["presses"] = [p.to_json() for p in self.expect_presses]
        if self.expect_screen_sha1:
            expect["screen_sha1"] = self.expect_screen_sha1
        return {
            "format": FORMAT,
            "version": VERSION,
            "created": self.created or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": self.notes,
            "rom": {"name": self.rom_name, "sha1": self.rom_sha1},
            "model": self.model,
            "warmup_frames": self.warmup,
            "frames": self.frames,
            "inputs": [{"f": f, "held": sorted(held, key=lambda n: BUTTONS[n])} for f, held in self.inputs],
            "pokes": [p.to_json() for p in self.pokes],
            "expect": expect,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1) + "\n")


def load_replay(path: Path) -> Replay:
    def fail(msg):
        raise ConvertError(path, msg)

    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read replay ({e}); record a new one in the lab")
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        fail(f"not a replay file: 'format' must be \"{FORMAT}\"")
    if doc.get("version") != VERSION:
        fail(f"replay version {doc.get('version')!r} is not supported (this lab reads version {VERSION}); re-record it")
    frames = doc.get("frames")
    if not isinstance(frames, int) or frames < 1:
        fail("'frames' must be a positive integer (the number of ticks to run)")
    warmup = doc.get("warmup_frames", WARMUP)
    if not isinstance(warmup, int) or warmup < 0:
        fail("'warmup_frames' must be a non-negative integer (ticks run before frame 0)")
    model = doc.get("model", "cgb")
    if model not in ("cgb", "dmg"):
        fail(f"'model' is '{model}'; it must be 'cgb' or 'dmg'")

    inputs = []
    last = -1
    for i, e in enumerate(doc.get("inputs", [])):
        held = e.get("held") if isinstance(e, dict) else None
        if not isinstance(e, dict) or not isinstance(e.get("f"), int) or not isinstance(held, list):
            fail(f"inputs[{i}] must look like {{\"f\": 12, \"held\": [\"a\"]}}")
        bad = [n for n in held if n not in BUTTONS]
        if bad:
            fail(f"inputs[{i}] has unknown button {bad[0]!r}; use {', '.join(BUTTONS)}")
        if not last < e["f"] < frames:
            fail(f"inputs[{i}].f = {e['f']} must be increasing and below 'frames' ({frames})")
        last = e["f"]
        inputs.append((e["f"], frozenset(held)))

    pokes = []
    for i, e in enumerate(doc.get("pokes", [])):
        ok = isinstance(e, dict) and all(k in e for k in ("f", "symbol", "offset", "type", "value"))
        if not ok or e["type"] not in TYPES or not all(isinstance(e[k], int) for k in ("f", "offset", "value")):
            fail(f"pokes[{i}] needs integer 'f', 'offset', 'value', a 'symbol' and a 'type' of {', '.join(TYPES)}")
        pokes.append(Poke(e["f"], e["symbol"], e["offset"], e["type"], e["value"], tuple(e.get("path", ()))))
    if [p.f for p in pokes] != sorted(p.f for p in pokes):
        fail("'pokes' must be sorted by 'f'")

    expect = doc.get("expect", {})
    presses = None
    if "presses" in expect:
        presses = []
        for i, p in enumerate(expect["presses"]):
            try:
                presses.append(Press(p["f"], names_to_mask(p["buttons"]), GRADES.index(p["grade"]), p["frames"]))
            except (KeyError, ValueError, TypeError):
                fail(f"expect.presses[{i}] must look like {{\"f\": 5, \"buttons\": [\"a\"], \"grade\": \"GOOD\", \"frames\": -1}}")
    rom = doc.get("rom", {})
    return Replay(
        frames, inputs, pokes, model, rom.get("name", ""), rom.get("sha1", ""), presses,
        expect.get("screen_sha1"), doc.get("created", ""), doc.get("notes", ""), warmup,
    )


class Recorder:
    """Collects one session's inputs and pokes, frame by frame, from boot."""

    def __init__(self, model: str = "cgb"):
        self.model = model
        self.inputs: list[tuple[int, frozenset]] = []
        self.pokes: list[Poke] = []
        self._held: frozenset = frozenset()

    def held(self, frame: int, buttons) -> None:
        """Call once per frame with the buttons held during that frame's tick."""
        buttons = frozenset(buttons)
        if buttons != self._held:
            self.inputs.append((frame, buttons))
            self._held = buttons

    def poke(self, frame: int, symbol: str, offset: int, ftype: str, value: int, path: tuple = ()) -> None:
        self.pokes.append(Poke(frame, symbol, offset, ftype, value, path))

    def finish(self, frames: int, presses: list[Press], screen_sha1: str, rom: Path | None) -> Replay:
        return Replay(
            frames, self.inputs, self.pokes, self.model,
            rom.name if rom else "", file_sha1(rom) if rom else "", presses, screen_sha1,
        )


class Player:
    """Feeds a replay into a running machine. Call `before_tick(frame)` ahead of each tick."""

    def __init__(self, replay: Replay, symbols: dict[str, int], press, release, write):
        self.replay = replay
        self.symbols = symbols
        self._press, self._release, self._write = press, release, write
        self._i = self._p = 0
        self.held: frozenset = frozenset()
        for p in replay.pokes:
            if p.symbol not in symbols:
                raise ConvertError(Path(replay.rom_name or "replay"), f"poke symbol '{p.symbol}' is not in the ROM's .noi; rebuild the DEBUG ROM")

    def before_tick(self, frame: int) -> None:
        r = self.replay
        while self._p < len(r.pokes) and r.pokes[self._p].f <= frame:
            p = r.pokes[self._p]
            self._write(self.symbols[p.symbol] + p.offset, p.encode())
            self._p += 1
        while self._i < len(r.inputs) and r.inputs[self._i][0] <= frame:
            self.set_held(r.inputs[self._i][1])
            self._i += 1

    def set_held(self, buttons: frozenset) -> None:
        for name in self.held - buttons:
            self._release(name)
        for name in buttons - self.held:
            self._press(name)
        self.held = buttons

    def release_all(self) -> None:
        self.set_held(frozenset())


class PressLogReader:
    """Reads new entries from the ROM's `_press_log` ring (src/gb/input.h) as they appear."""

    SIZE = 16  # PRESS_LOG_SIZE
    ENTRY = 4  # frame, buttons, grade, frames

    def __init__(self, symbols: dict[str, int], read):
        self.log = symbols.get("_press_log")
        self.head = symbols.get("_press_log_head")
        self._read = read
        self.last = 0
        self.available = self.log is not None and self.head is not None

    def resync(self) -> None:
        self.last = self._read(self.head, 1)[0] if self.available else 0

    def poll(self, frame: int) -> list[Press]:
        if not self.available:
            return []
        head = self._read(self.head, 1)[0]
        new = (head - self.last) & 0xFF
        if not new:
            return []
        first = self.last
        if new > self.SIZE:  # overran the ring between polls; only the newest SIZE survive
            first = (head - self.SIZE) & 0xFF
            new = self.SIZE
        out = []
        for k in range(new):
            slot = (first + k) & (self.SIZE - 1)
            raw = self._read(self.log + slot * self.ENTRY, self.ENTRY)
            frames = raw[3] - 256 if raw[3] > 127 else raw[3]
            out.append(Press(frame, raw[1], min(raw[2], 2), frames))
        self.last = head
        return out


def file_sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def screen_sha1(pb) -> str:
    return hashlib.sha1(pb.screen.ndarray.tobytes()).hexdigest()


def new_pyboy(rom: Path, model: str = "cgb", window: str = "null", sound: bool = False, volume: int = 100, scale: int = 3):
    """A PyBoy on `rom` with blank cartridge RAM, so a boot never depends on a leftover .ram file."""
    from pyboy import PyBoy

    return PyBoy(
        str(rom), window=window, cgb=(model == "cgb"), sound_emulated=sound, sound_volume=volume, scale=scale,
        ram_file=io.BytesIO(BLANK_SRAM),
    )


class PbMemory:
    """Byte-level read/write on a PyBoy's address space."""

    def __init__(self, pb):
        self.pb = pb

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self.pb.memory[addr : addr + n])

    def write(self, addr: int, data: bytes) -> None:
        self.pb.memory[addr : addr + len(data)] = list(data)


@dataclass
class ReplayResult:
    presses: list[Press]
    screen_sha1: str
    frames: int
    mismatches: list[str]

    @property
    def ok(self) -> bool:
        return not self.mismatches


def compare(replay: Replay, presses: list[Press], screen: str) -> list[str]:
    out = []
    if replay.expect_presses is not None:
        want, got = replay.expect_presses, presses
        for i in range(max(len(want), len(got))):
            w = want[i] if i < len(want) else None
            g = got[i] if i < len(got) else None
            if w != g:
                out.append(f"press #{i}: expected {w or 'none'}, got {g or 'none'}")
                if len(out) >= 10:
                    out.append("(further press differences not shown)")
                    break
    if replay.expect_screen_sha1 and replay.expect_screen_sha1 != screen:
        out.append("final screen differs from the recorded one")
    return out


def run_replay(rom: Path, replay: Replay, symbols: dict[str, int]) -> ReplayResult:
    """Replay headless at full speed from a fresh boot and compare with the recorded expectations."""
    pb = new_pyboy(rom, replay.model)
    pb.set_emulation_speed(0)
    try:
        pb.tick(replay.warmup, False, False)
        mem = PbMemory(pb)
        reader = PressLogReader(symbols, mem.read)
        player = Player(replay, symbols, pb.button_press, pb.button_release, mem.write)
        presses: list[Press] = []
        for frame in range(replay.frames):
            player.before_tick(frame)
            pb.tick(1, True, False)  # render every frame: skipping some changes later screens
            presses += reader.poll(frame)
        sha = screen_sha1(pb)
    finally:
        pb.stop(save=False)
    return ReplayResult(presses, sha, replay.frames, compare(replay, presses, sha))
