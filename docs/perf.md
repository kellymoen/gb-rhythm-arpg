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

## Lessons

- The first `hud_update` called `beat_ticks_until_slot` (16-bit multiply/divide) for each of 8 pips
  and took ~230 lines, so the main loop ran at 30 fps. The fix steps by addition from one 8-bit divide.
- The first `beat_judge` used 32-bit divide and multiply and ran the ISR ~90 lines into the visible
  frame on every press. The fix is 16-bit math with subtraction loops.
- Writing text while the LCD is on is slow, so scenes do at most one text job per frame.

## Debt

- `music_update` is plain SDCC C. Costing 8–25% of a frame just to play music is too much once
  combat needs the CPU. If M2/M3 budgets get tight, rewrite the event loop in assembly; a 3–5x
  saving is likely.
