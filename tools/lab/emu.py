"""The lab's emulator loop: PyBoy plus live WRAM tables, press log, recording and replay.

Everything here runs on the main thread (SDL requires it on macOS). The web server's threads never
touch PyBoy; they queue a function with `Machine.call()` and the loop runs it between two frames.
"""

import io
import queue
import time
from collections import deque
from concurrent.futures import Future
from pathlib import Path

from gbtools.errors import ConvertError

from .audio import GB_FPS, AudioOut
from .descriptor import Field, Table
from .replay import (
    GRADES, WARMUP, Player, PbMemory, Press, PressLogReader, Recorder, Replay, compare, load_replay, mask_to_names,
    new_pyboy, screen_sha1,
)
from .symbols import load_symbols
from .tomlio import save_values

# Where the graph reads the grading windows and latency from (ADR 0004 names); fields may be absent.
WINDOW_PATHS = {"perfect": ("timing", "perfect_window"), "good": ("timing", "good_window"), "latency": ("timing", "latency_offset")}


def _keyboard_buttons():
    """Buttons PyBoy's SDL window sees as held (the same keys it maps), or an empty set."""
    import sdl2

    keys = sdl2.SDL_GetKeyboardState(None)
    names = {
        "up": sdl2.SDL_SCANCODE_UP, "down": sdl2.SDL_SCANCODE_DOWN, "left": sdl2.SDL_SCANCODE_LEFT,
        "right": sdl2.SDL_SCANCODE_RIGHT, "a": sdl2.SDL_SCANCODE_A, "b": sdl2.SDL_SCANCODE_S,
        "start": sdl2.SDL_SCANCODE_RETURN, "select": sdl2.SDL_SCANCODE_BACKSPACE,
    }
    return frozenset(n for n, sc in names.items() if keys[sc])


class Machine:
    def __init__(
        self, rom: Path, tables: list[Table], repo: Path, replay_dir: Path, *, window: str = "SDL2",
        audio: bool = True, audio_frames: float = 1.5, realtime: bool = True, scale: int = 4,
    ):
        self.rom, self.tables, self.repo, self.replay_dir = rom, tables, repo, replay_dir
        self.windowed = window != "null"
        self.realtime = realtime
        self.symbols = load_symbols(rom)
        self.warnings: list[str] = []
        self.fields: dict[str, tuple[Table, Field]] = {}
        for t in tables:
            if t.symbol not in self.symbols:
                self.warnings.append(f"{t.file.name}: symbol '{t.symbol}' is not in {rom.with_suffix('.noi').name}; its sliders are disabled")
                continue
            for f in t.fields:
                self.fields[f.id] = (t, f)

        self.audio = AudioOut(48000, audio_frames) if audio else None
        if self.audio and not self.audio.ok:
            self.warnings.append("no audio output device could be opened; running muted")
            self.audio = None
        # PyBoy's own audio path is silenced when ours is used (it drifts; docs/lab-audio-spike.md).
        self.pb = new_pyboy(rom, "cgb", window, sound=self.audio is not None, volume=0, scale=scale)
        self.pb.set_emulation_speed(0)  # we pace the loop: by the audio queue, else by the clock
        self.mem = PbMemory(self.pb)
        self.reader = PressLogReader(self.symbols, self.mem.read)
        if not self.reader.available:
            self.warnings.append("_press_log is not in the ROM (build with DEBUG=1); the press graph is empty")
        self.pb.tick(WARMUP, False, False)  # boot animation + ROM init; this is frame 0 of every replay
        snap = io.BytesIO()
        self.pb.save_state(snap)
        self._boot_state = snap.getvalue()

        self.frame = 0
        self.seq = 0
        self.presses: deque = deque(maxlen=4000)
        self.virtual: frozenset = frozenset()
        self._applied_virtual: frozenset = frozenset()
        self.recorder: Recorder | None = None
        self.player: Player | None = None
        self.replay: Replay | None = None
        self.replay_name = ""
        self.replay_presses: list[Press] = []
        self.replay_result: dict | None = None
        self._restore_values: dict[str, int] = {}
        self._cmds: queue.Queue = queue.Queue()
        self.running = True
        self.closed = False
        self._next = time.perf_counter()
        self._fps_t, self._fps_n, self.fps = time.perf_counter(), 0, 0.0
        self.reader.resync()

    # ---- cross-thread access -------------------------------------------------------------------
    def call(self, fn, timeout: float = 3.0):
        """Run `fn()` on the emulator thread between two frames and return its result."""
        if self.closed:
            raise RuntimeError("the lab's emulator has stopped")
        fut: Future = Future()
        self._cmds.put((fn, fut))
        return fut.result(timeout)

    def _drain(self) -> None:
        while True:
            try:
                fn, fut = self._cmds.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(fn())
            except BaseException as e:  # reported to the HTTP caller, never kills the loop
                fut.set_exception(e)

    # ---- table access --------------------------------------------------------------------------
    def addr(self, f: Field, table: Table) -> int:
        return self.symbols[table.symbol] + f.offset

    def read_field(self, table: Table, f: Field) -> int:
        return f.decode(self.mem.read(self.addr(f, table), f.size))

    def values(self) -> dict[str, int]:
        return {fid: self.read_field(t, f) for fid, (t, f) in self.fields.items()}

    def write_field(self, table: Table, f: Field, value: int, record: bool = True) -> None:
        self.mem.write(self.addr(f, table), f.encode(value))
        if record and self.recorder:
            self.recorder.poke(self.frame, table.symbol, f.offset, f.type, value, f.path)

    def set_value(self, fid: str, value: int) -> int:
        if fid not in self.fields:
            raise KeyError(f"unknown field '{fid}'")
        table, f = self.fields[fid]
        if self.player:
            raise RuntimeError("a replay is playing; changing values would break it. Cancel the replay first")
        self.write_field(table, f, value)
        return self.read_field(table, f)

    def reset(self, table_name: str | None = None) -> int:
        if self.player:
            raise RuntimeError("a replay is playing; cancel it first")
        n = 0
        for t, f in self.fields.values():
            if table_name in (None, t.name) and self.read_field(t, f) != f.default:
                self.write_field(t, f, f.default)
                n += 1
        return n

    def save(self, table_name: str | None = None) -> dict:
        """Write current values into each source TOML; the saved values become the new defaults."""
        out = {}
        for t in self.tables:
            if table_name not in (None, t.name):
                continue
            edits = [(f, self.read_field(t, f)) for f in t.fields if f.id in self.fields]
            if not edits:
                continue
            out[t.name] = save_values(self.repo / t.source, edits)
            for f, v in edits:
                f.default = v
        return out

    def windows(self) -> dict:
        vals = {}
        for key, path in WINDOW_PATHS.items():
            for t in self.tables:
                f = t.find(path)
                if f and f.id in self.fields:
                    vals[key] = self.read_field(t, f)
        return vals

    # ---- sessions ------------------------------------------------------------------------------
    def _boot(self) -> None:
        self.pb.load_state(io.BytesIO(self._boot_state))
        self.frame = 0
        self.virtual = self._applied_virtual = frozenset()
        self.reader.resync()

    def _overrides(self) -> list[tuple[Table, Field, int]]:
        """Fields whose live value differs from a fresh boot's."""
        cur = {fid: self.read_field(t, f) for fid, (t, f) in self.fields.items()}
        self._boot()
        return [(t, f, cur[fid]) for fid, (t, f) in self.fields.items() if cur[fid] != self.read_field(t, f)]

    def restart(self) -> None:
        """Reboot the ROM, then re-apply the slider values that differ from its defaults."""
        self.stop_replay()
        self.recorder = None
        for t, f, v in self._overrides():
            self.write_field(t, f, v, record=False)

    def start_recording(self) -> None:
        self.stop_replay()
        overrides = self._overrides()
        self.recorder = Recorder("cgb")
        for t, f, v in overrides:
            self.write_field(t, f, v)  # recorded as frame-0 pokes: the replay starts from ROM defaults

    def stop_recording(self, name: str) -> Path:
        if not self.recorder:
            raise RuntimeError("not recording")
        rec, self.recorder = self.recorder, None
        presses = [Press(p["f"], p["raw_buttons"], p["raw_grade"], p["frames"]) for p in self.presses if p["rec"] is rec]
        replay = rec.finish(self.frame, presses, screen_sha1(self.pb), self.rom)
        path = self.replay_dir / f"{name}.json"
        replay.save(path)
        return path

    def start_replay(self, name: str) -> None:
        if self.recorder:
            raise RuntimeError("recording; stop the recording first")
        self.play(load_replay(self.replay_dir / f"{name}.json"), name)

    def play(self, replay: Replay, name: str) -> None:
        """Reboot and replay from frame 0; when it ends the sliders return to their previous values."""
        if replay.warmup != WARMUP:
            raise RuntimeError(f"{name} warms up for {replay.warmup} frames but the lab boots after {WARMUP}; use `python -m lab replay` instead")
        self.stop_replay()
        self._restore_values = self.values()
        self._boot()
        self.replay, self.replay_name, self.replay_presses, self.replay_result = replay, name, [], None
        self.player = Player(
            replay, self.symbols, self.pb.button_press, self.pb.button_release, self.mem.write,
        )

    def stop_replay(self, restore: bool = True) -> None:
        if self.player:
            self.player.release_all()
            self.player = None
        if restore and self._restore_values:
            for fid, v in self._restore_values.items():
                t, f = self.fields[fid]
                if self.read_field(t, f) != v:
                    self.write_field(t, f, v, record=False)
        self._restore_values = {}

    def set_virtual(self, buttons) -> None:
        self.virtual = frozenset(buttons)

    # ---- the loop ------------------------------------------------------------------------------
    def _pace(self) -> None:
        if self.audio:
            self.audio.wait_for_room()
        elif self.realtime:
            self._next += 1 / GB_FPS
            delay = self._next - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                self._next = time.perf_counter()

    def step(self) -> bool:
        """Run one frame. Returns False when the window was closed."""
        self._drain()
        self._pace()
        f = self.frame
        if self.player:
            self.player.before_tick(f)
        else:
            for name in self.virtual - self._applied_virtual:
                self.pb.button_press(name)
            for name in self._applied_virtual - self.virtual:
                self.pb.button_release(name)
            self._applied_virtual = self.virtual

        before = self.pb.frame_count
        alive = self.pb.tick(1, True, self.audio is not None)
        if self.pb.frame_count == before:  # paused from PyBoy's keyboard: nothing ran
            return alive
        if self.audio:
            self.audio.push(self.pb.sound.ndarray)

        for p in self.reader.poll(f):
            self._log_press(f, p)
        if self.recorder:
            held = (_keyboard_buttons() if self.windowed else frozenset()) | self.virtual
            self.recorder.held(f, held)
        self.frame += 1
        if self.player and self.frame >= self.replay.frames:
            self._finish_replay()

        self._fps_n += 1
        now = time.perf_counter()
        if now - self._fps_t >= 1.0:
            self.fps, self._fps_t, self._fps_n = self._fps_n / (now - self._fps_t), now, 0
        return alive

    def _log_press(self, f: int, p: Press) -> None:
        self.seq += 1
        self.presses.append({
            "seq": self.seq, "f": f, "buttons": mask_to_names(p.buttons), "grade": GRADES[p.grade],
            "frames": p.frames, "windows": self.windows(), "rec": self.recorder, "raw_buttons": p.buttons,
            "raw_grade": p.grade,
        })
        if self.player:
            self.replay_presses.append(p)

    def _finish_replay(self) -> None:
        mismatches = compare(self.replay, self.replay_presses, screen_sha1(self.pb))
        self.replay_result = {"name": self.replay_name, "ok": not mismatches, "mismatches": mismatches}
        self.stop_replay(restore=True)

    def run(self, on_exit=None) -> None:
        try:
            while self.running and self.step():
                pass
        finally:
            self.closed = True
            self.running = False
            if on_exit:
                on_exit()
            while not self._cmds.empty():
                _, fut = self._cmds.get_nowait()
                fut.set_exception(RuntimeError("the lab's emulator has stopped"))
            if self.audio:
                self.audio.close()
            self.pb.stop(save=False)

    # ---- status for the UI ---------------------------------------------------------------------
    def status(self) -> dict:
        st = {
            "frame": self.frame, "fps": round(self.fps, 1), "windowed": self.windowed,
            "mode": "replay" if self.player else "recording" if self.recorder else "live",
            "recording_frames": self.frame if self.recorder else 0,
            "replay": {"name": self.replay_name, "frame": self.frame, "total": self.replay.frames} if self.player else None,
            "replay_result": self.replay_result,
            "warnings": self.warnings,
        }
        if self.audio:
            st["audio"] = {
                "driver": self.audio.driver, "queued_frames": round(self.audio.queued_frames(), 2),
                "underruns": self.audio.underruns, "target_frames": self.audio.target,
            }
        return st

    def screen_png(self) -> bytes:
        buf = io.BytesIO()
        self.pb.screen.image.save(buf, "PNG")
        return buf.getvalue()
