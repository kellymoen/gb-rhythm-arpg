"""Step-0 spike: how good is PyBoy's real-time audio for judging rhythm feel?

Runs the DEBUG ROM in PyBoy's SDL2 window (real-time, sound on) for N seconds and records, per frame,
how long `tick()` took and how many audio frames SDL still has queued (SDL_GetQueuedAudioSize). It
reports pacing jitter, buffer depth (= audio lag behind the picture) and underruns (queue hits zero).
Findings are written up in docs/lab-audio-spike.md.

    PYTHONPATH=tools uv run python -m lab.audio_spike [rom] [seconds] [own [target_frames]]
"""

import statistics
import sys
import time
from pathlib import Path

import sdl2
from pyboy import PyBoy

from lab.audio import AudioOut

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    rom = Path(argv[0]) if argv else REPO / "build/beatarpg-debug.gbc"
    seconds = float(argv[1]) if len(argv) > 1 else 10.0
    own = len(argv) > 2 and argv[2] == "own"  # lab/audio.py as the clock instead of PyBoy's pacing
    pb = PyBoy(str(rom), window="SDL2", sound_emulated=True, sound_volume=0 if own else 100, cgb=True)
    pb.set_emulation_speed(0 if own else 1)
    out = AudioOut(pb.sound.sample_rate, target_frames=float(argv[3]) if len(argv) > 3 else 2.0) if own else None
    # PyBoy is Cython-compiled, so its SDL window plugin is not reachable from Python. SDL hands out
    # audio device ids from 2 upwards; PyBoy opens exactly one, so find the one with a queue.
    pb.tick(30)
    dev = next((d for d in range(2, 8) if sdl2.SDL_GetQueuedAudioSize(d) > 0), None)
    print(f"audio driver: {sdl2.SDL_GetCurrentAudioDriver()}; queue device id: {dev}")
    if own:
        dev = out.dev
        print(f"own output: ok={out.ok} device buffer {out.device_ms:.1f} ms, target {out.target} frames")
    if dev is None:
        print("no audio queue found (no audio device?)")
    spf = pb.sound.sample_rate / 59.7275
    durs, queued, underruns, resets = [], [], 0, 0
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        if out:
            out.wait_for_room()
        t0 = time.perf_counter()
        if not pb.tick():
            break
        if out:
            out.push(pb.sound.ndarray)
        durs.append((time.perf_counter() - t0) * 1000)
        if dev is not None:
            q = sdl2.SDL_GetQueuedAudioSize(dev) / 2 / spf  # bytes -> frames (S8 stereo)
            queued.append(q)
            underruns += q < 0.3
            resets += len(queued) > 1 and queued[-2] - q > 1.5  # SDL_ClearQueuedAudio by PyBoy
    pb.stop(save=False)
    n = len(durs)
    print(f"{n} frames in {seconds:.0f}s = {n / seconds:.2f} fps (target 59.73)")
    print(f"frame interval ms: mean {statistics.mean(durs):.2f} stdev {statistics.pstdev(durs):.2f} "
          f"p99 {sorted(durs)[int(n * .99)]:.2f} max {max(durs):.2f}")
    if queued:
        q = queued[60:] or queued  # skip startup
        print(f"audio queue (frames): mean {statistics.mean(q):.2f} min {min(q):.2f} max {max(q):.2f} "
              f"-> sound for a frame starts ~{(statistics.mean(q) - 1) * 16.74:.0f} ms after its picture "
              f"(range {(min(q) - 1) * 16.74:.0f}-{(max(q) - 1) * 16.74:.0f}), underruns {underruns}, buffer resets {resets}")
        slow = sum(d > 20 for d in durs)
        print(f"frames over 20 ms: {slow}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
