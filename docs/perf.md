# Performance notes

A frame is 154 scanlines, about 114 CPU cycles (M-cycles) each, at the DMG speed we budget for
(ADR 0001). Numbers below were measured in PyBoy by hooking function entries and reading `LY`. The
scripts are in the M1 history; `tests/rom/test_rhythmtest.py::test_main_loop_never_misses_a_frame`
guards the result.

## M1 (rhythm-test scene, 2026-10-27)

| Work | Scanlines |
|------|-----------|
| `music_update` (VBlank ISR), no note events | ~13 |
| `music_update` on 8th-note frames (3–4 events) | ~27–36 |
| `input_poll` + `beat_judge` + `music_hit` on a press | ~20 |
| Main loop: `hud_update` + `fx_update` | ~21 |
| One BG text job (`text_print`/`text_print_int`, LCD on) | ~10–15 each |

## M2 audio: SFX driver and musical hits (2026-10-29)

Measured in PyBoy on the placeholders-only CGB ROM over 1000 frames per run, with PyBoy hooks on
`_music_update`, `_sfx_update`, `_input_poll` and `_hud_update` reading `LY`. Runs covered the
rhythm-test song (128 BPM), the combat song (120→140 BPM), each idle and with an effect requested every
9 frames on rotating channels. The ISR order is `music_update`, `sfx_update`, `input_poll`, then
`sfx_hit` on an on-beat press.

| Work (VBlank ISR) | Scanlines |
|-------------------|-----------|
| `music_update`, typical frame | ~13 (p95 ~36) |
| `music_update`, one song event | ~4.5 each (SDCC C) |
| `music_update` on a song's first frame | 53 (was 108) |
| `music_update` on the loop frame | 71 (was 114) |
| `sfx_update`, no effect running | 0–1 |
| `sfx_update`, stepping a running effect | 1–4 |
| `sfx_update`, starting an effect | 13–15 (WAVE, loading its shape: 23–25) |
| music + sfx, busiest frames with effects | median 16, p95 ~35, max 75 (loop frame + effect start) |
| Press: `input_poll` → main loop resumes, with musical hit | ~29 (20 without; `sfx_hit` ≈ 9) |

**ISR audio exceeds ~30 scanlines on busy frames.** The p95 is ~35. The loop frame takes 71–75, and the
song's first frame 53. Each event costs ~4.5 lines because SDCC compiles `run_event`'s struct-pointer
code into long stack shuffles. The M2 frame-budget test (`tests/rom/test_audio.py`) now runs past the
combat loop point. It failed there at 114 lines, before the converter changes below.

Fixed in the converter (cheap, no driver change):
- No `EV_LOOP` event when the loop point is the start (`music_play` already points the loop there).
- Loop restores (instrument, duty, bend, vibrato, tempo) are emitted only for values the song changes
  after the loop point.
- No `EV_OFF` at the end when a note starts the loop (it retriggers anyway).

Still open: an assembly `run_event`/`music_update` (3–5× likely) is the next step if combat frames get
tight. A song with many simultaneous events on one frame (e.g. all four channels change instrument and
start notes on the downbeat) costs ~4.5 lines per event until then.

## Lessons

- The first `hud_update` called `beat_ticks_until_slot` (16-bit multiply/divide) for each of 8 pips
  and took ~230 lines, so the main loop ran at 30 fps. The fix steps by addition from one 8-bit divide.
- The first `beat_judge` used 32-bit divide and multiply and ran the ISR ~90 lines into the visible
  frame on every press. The fix is 16-bit math with subtraction loops.
- Writing text while the LCD is on is slow, so scenes do at most one text job per frame.

## Debt

- `music_update` is plain SDCC C. Costing 8–25% of a frame just to play music is too much once
  combat needs the CPU (M2 numbers above: ~4.5 lines per event, 71 on a loop frame). If M2/M3
  budgets get tight, rewrite the event loop in assembly; a 3–5x saving is likely.
- `sfx_update` starting an effect (13–15 lines) and `sfx_hit` (~9) are SDCC C too; they would shrink
  with the same treatment.
- `chan_freq` (pitch bend) and `vibrato` call `__mulint`/`__mulschar` in the ISR, against the
  no-16-bit-multiply rule. Only channels with bend or vibrato active pay for it.
