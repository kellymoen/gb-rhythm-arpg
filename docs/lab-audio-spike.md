# Feel lab audio spike

Question: is PyBoy's real-time audio good enough to judge rhythm feel by ear in the lab?
Script: `tools/lab/audio_spike.py` (`PYTHONPATH=tools uv run python -m lab.audio_spike [rom] [seconds] [own [target_frames]]`).
Measured 2026-10-29 on the author's Mac (Apple silicon, built-in output, CoreAudio, PyBoy 2.8.1, SDL 2.32.10),
DEBUG ROM on the main menu, 30 s runs. I cannot listen from here: everything below is **measured queue
depth and frame pacing, not an ear test**, so the numbers are what the author should sanity-check by ear.

## How PyBoy outputs sound

With `window="SDL2"` and sound on, PyBoy's SDL window plugin opens one SDL audio device (stereo, signed 8-bit,
48 kHz, 128-sample device buffer) and after every frame calls `SDL_QueueAudio` with that frame's samples.
It paces the emulator from the queue: it sleeps only while more than **3 frames** (~50 ms) are queued, and
`SDL_ClearQueuedAudio`s the whole queue if it ever exceeds 7 frames. Pulling `pb.sound.ndarray` yourself is
possible (raw int8 stereo per frame) and that is what the lab does.

## Findings

| | PyBoy's own SDL audio | lab output, target 1.5 frames | lab output, target 1.0 frame |
|---|---|---|---|
| frame pacing | 60.40 fps (limiter targets 60.0, the Game Boy makes 59.73) | 59.87 fps (the audio device is the clock) | 59.83 fps |
| sound starts after its picture | **~66 ms mean, wandering ~35 to ~100 ms** | **~20 ms, 7 to 25** | ~11 ms, 6 to 17 |
| buffer flushes (audible glitch) | **2-3 per 30-40 s** (queue grows ~0.6 frame/s until it hits 7) | 0 | 0 |
| underruns | 0 | 0 | 0 |
| frames over 20 ms to emulate | 1-2 (first frames) | 0 | 0 |

- **Why PyBoy's drifts.** The limiter paces at 60 fps but the Game Boy produces audio at 59.73 frames/s, so
  the queue fills ~1% faster than the device drains it, climbs from 3 to 7 frames, and is then flushed.
  The audio-to-picture offset is therefore a sawtooth, not a constant, and there is a dropout every ~13 s.
  That is poison for judging timing: the thing the author is tuning (a few frames of latency) is smaller than
  the drift.
- **Emulation headroom.** Emulating a frame takes ~0.8 ms (p99 2 ms, max 13 ms at startup), ~20x real time,
  so running the loop on the audio clock is safe even with 1 frame of queue.
- **Fixed output path.** The device buffer is 5.3 ms (256 samples requested; CoreAudio honoured it). The OS
  and hardware path behind it (built-in speakers: roughly 5-15 ms; wired headphones similar; **Bluetooth adds
  100-250 ms and makes the lab unusable for feel**) is not measurable from SDL.
- **Jitter** of the lab's audio-to-picture offset is bounded but not tiny: 7-25 ms observed at the default
  target (6-17 ms at 1.0 frame). CoreAudio drains the queue in 5.3 ms chunks and the lab polls it every 0.5 ms,
  so the offset wobbles by up to roughly +/-9 ms around ~16 ms with no drift. That is half a frame of wobble
  on top of a constant, versus PyBoy's 65 ms of sawtooth; it is fine for the lab's purpose (judging a
  latency offset to within a frame or two), not a substitute for the real console.

## Recommendation

PyBoy's built-in audio is **not** good enough to judge rhythm feel (wandering 35-100 ms lag, a glitch every
~13 s). The lab therefore uses its own output: PyBoy runs unthrottled with its audio muted, each frame's
samples go to our own SDL queue, and the **audio device is the frame clock** (`tools/lab/audio.py`). That makes
audio lag bounded and drift-free (~16 ms plus or minus 9 by default; `--audio-frames` trades latency for
dropout safety), with no flushes. What matters is that the lag does not wander: any steady lag is absorbed
by `timing.latency_offset`.

Caveats to keep in mind:

1. **The lab's `latency_offset` is the lab's, not SameBoy's.** Its value includes the lab's audio lag, the
   display path and the keyboard. ADR 0008 makes SameBoy the reference and the default in `data/tuning.toml`
   is SameBoy's. Use the lab to tune *windows, steps and everything else*; calibrate `latency_offset` for the
   release build with the in-ROM calibration screen on the target emulator (or compare the lab's number to a
   calibration run in SameBoy once and keep the difference in mind).
2. **Keyboard latency** (macOS key event to PyBoy) adds up to one frame on top: input is read at the start of
   each tick, same as SameBoy's per-frame polling.
3. **Verdict if the ear disagrees.** If, listening, the lab still feels smeared, run with `--mute` (no audio,
   wall-clock pacing) or ignore the lab's sound and judge feel in SameBoy: the sliders, the press graph and
   replays work identically without audio. Sharing live state with SameBoy is not possible (it is a separate
   process with no memory hook), so the lab cannot drive SameBoy; tune in the lab, save to the TOML, rebuild,
   and play the result in SameBoy to confirm.
