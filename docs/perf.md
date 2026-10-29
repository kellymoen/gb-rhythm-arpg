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

## M2 combo matcher (2026-10-29)

Measured with TIMA in a scratch ROM, interrupts off, banked call included.

| Call | Scanlines |
|------|-----------|
| `combo_tick`, idle | 1.4 |
| `combo_tick`, in a string | 7.4 |
| `combo_tick`, break | 9.0 |
| Press that starts, continues or finishes a string | 17–19 |
| Worst press (break and restart) | 28.8 |
| `beat_judge` at latency 15 | 12.9 (no multiply or divide helpers any more) |

If the combat frame gets tight, the next lever is `probe()` in assembly.

## M2 sprite runtime (2026-10-29)

Measured at DMG speed in the combat-scene sprite viewer under random button spam.

| Work | Scanlines (avg / max) |
|------|-----------|
| Character update, no event | 1–2 |
| Update that shows a new frame | 24 / 31 |
| `spriteanim_play` | 25 / 29 |
| `spriteanim_face` to another drawn facing | 22 / 26 (a mirror-only turn is nearly free) |
| `oam_begin` + 2 draws + `oam_end` | 13 / 16 |
| Tile streaming, HBlank copy with the LCD on | ~37 per 192 B (~5 B per line) |
| Tile streaming, LYC=143 interrupt into VBlank | ~80 B per VBlank |
| GBDK `set_sprite_data` with the LCD on | ~64 per 192 B |

A 12-tile frame therefore shows 1–2 video frames after it is due, and frames already sitting in a
slot cost nothing. Rule for scenes: at most one costly anim start, turn or new frame shown per
frame; skip costly work when the loop starts late (LY ≥ 36); stop streaming at LY 124. The
combat-scene viewer's main loop ends at LY 80 (median), 139 at worst.

The song-loop spike (106–112 lines in the ISR, measured before the converter fix above) no longer
drops frames: the rhythm-test and combat scenes ran 1400 frames past the loop point with no misses.

## M2 combat scene (2026-10-29)

Measured in PyBoy on the placeholders-only CGB and DMG ROMs (identical numbers) over 1500 frames of
random spam: A/B on a quarter of the frames, A+B, walking in 8 directions, the dummy striking every 4
beats, past the tempo change and the song's loop. "Work" runs from the loop's start (after `vsync()`
returns, i.e. after the VBlank ISR) to the start of tile streaming.

| | Scanlines (median / p95 / max) |
|-|-----------|
| Loop start (where the VBlank ISR ends) | 16 / 43 / 70 |
| Work, all frames | 69 / 95 / 117 |
| Work ends at LY | 88 / 112 / 129 |
| `vsync()` called at LY (streaming fills to 120, late OAM rewrite) | 98 / - / 140 |
| Missed frames | 0 |

| Frame type | Work median / max |
|------------|-----------|
| Attack or dodge start + a press fed to the matcher | 89 / 117 |
| Attack or dodge start | 90 / 106 |
| Hit frame (`combat_on_hit_frame`: hitbox test, hitstop, flash, counters) | 84 / 102 |
| Press fed to the matcher | 80 / 101 |
| Text job | 60 / 90 |
| Nothing special (HUD, OAM, popups, possibly a new anim frame) | 54 / 88 |

Fixed costs per frame: `fx_update` + clock ~7, `oam_begin`/2 draws/`oam_end` ~14, `hud_update` ~11
(was ~21: two `__divuchar` calls, now gone), `combat_ui_update` ~1-2 (OAM touched only on change),
DEBUG timing overlay up to ~11 after a press. The matcher's tick costs ~27 lines on a frame where it
resolves a held-back press into events.

A press's attack starts 2 frames after the press (the `dodge_grace` hold-back), never later in the
scripted strings: scheduling added no delay. Its first frame shows 1-2 frames after that (streaming).

**Scheduling policy** (`src/scenes/combatflat.c`): presses are graded in the ISR, so everything here
only moves visuals (and schedules musical hits, below). Each costly step starts only before its LY
limit: another press to the matcher < 64, the matcher's tick < 80 (and never while presses are still
queued), the early landing of a held-back press (`combo_land`, its musical hit) < 44 and not on a
frame whose player hit frame is due, the player's attack/dodge
start < 68 (first, before anims update; its anim then advances from the next frame with the ticks
carried), a new anim frame shown < 60, one other anim start/turn < 64, a text job < 100 (only when
nothing costly ran), the DEBUG overlay < 112, streaming until 120, a late OAM rewrite < 126. A loop
starting at LY >= 36 leaves presses queued and does nothing costly; at >= 64 it only draws, and both
characters' song ticks carry to the next frame (anims stay on the beat; a hit frame lands a frame
late). The dummy's update is skipped (ticks carried, at most 24) when it would cost a call on a frame
that already showed a new frame.

### Musical hits after the review fixes (2026-10-29)

Hits now follow the combo matcher (`gb/isr.h`). The main loop schedules a step's hit as soon as the
matcher lands its press; the VBlank ISR plays it once `dodge_grace` frames have passed with no other
button (so a dodge plays none) and, with `feedback.quantize_hits`, once the beat clock reaches the
step slot's start (a compare of beat and tick, no multiply).

The landing used to happen when the held-back press committed (the tick 2 frames after the press,
~27 lines). Doing it in `combo_press` on the press's own frame overran frames under button spam: the
worst landing (break + restart) is ~33 lines plus ~7 for `isr_hit_schedule`, and a frame that also
reached the player's hit frame (~28) ended past line 154. So `combo_press` still only holds the press
(cheap) and `combo_land` lands it early when there is room: before LY 44, never on a frame whose player
hit frame is due (`hit_frame_due`: the attack's musical position reaches its hit frame this frame).
Otherwise the commit lands it, as before.

Press to hit sound, measured in PyBoy (`tests/rom/test_combat.py::test_hit_latency`, and 1500 frames
of the spam run with quantize off, CGB and DMG identical):

| Press | `quantize_hits = 1` | `quantize_hits = 0` |
|-------|------------------|------------------|
| Early (5 frames before its slot) | on the slot: 5 frames, the first frame at or after the slot's start | 2 frames |
| On time | 2 frames (`dodge_grace`) | 2 frames |
| Late (4 frames) | 2 frames | 2 frames |
| Under spam (all presses) | - | 2 frames 95%, 3 frames at worst |

`dodge_grace` frames is the floor for an on-time or late press: before then a B could still turn the
A into a dodge. Before these fixes every non-OFFBEAT press played on its own frame (0 frames), at the
previous step's pitch, dodges and ignored presses included.

Spam run after the fixes: `vsync()` called at LY 105 / 131 / 141 (median / p95 / max), no missed
frames (was 98 / - / 140). The ISR's hit check is a few lines; `sfx_hit` still ~9 when a hit plays.

Fixed on the way: the LYC=143 VBlank stream handler assumed whole tiles; after an HBlank copy stopped
inside a tile it wrapped `units` and overwrote both characters' slots. It now finishes the partial
tile first.

## Lessons

- The first `hud_update` called `beat_ticks_until_slot` (16-bit multiply/divide) for each of 8 pips
  and took ~230 lines, so the main loop ran at 30 fps. The fix steps by addition from one 8-bit divide.
- The first `beat_judge` used 32-bit divide and multiply and ran the ISR ~90 lines into the visible
  frame on every press. The fix is 16-bit math with subtraction loops.
- Writing text while the LCD is on is slow, so scenes do at most one text job per frame.

## Bank 0

`romusage build/beatarpg.map -g`, release ROM. Before the M2 review fixes: 3733 bytes free. The
musical-hit scheduler in `isr.c` (bank 0: the ISR reads it) cost ~340 (3395 free). Banking `menu.c`,
`scene.c` and `core/calib.c` (only `menu_run` stays in bank 0, as a NONBANKED wrapper) brought it to
4301 free (DEBUG ROM: 2035 -> 2940).

## Debt

- `music_update` is plain SDCC C. Costing 8–25% of a frame just to play music is too much once
  combat needs the CPU (M2 numbers above: ~4.5 lines per event, 71 on a loop frame). If M2/M3
  budgets get tight, rewrite the event loop in assembly; a 3–5x saving is likely.
- `sfx_update` starting an effect (13–15 lines) and `sfx_hit` (~9) are SDCC C too; they would shrink
  with the same treatment.
- `chan_freq` (pitch bend) and `vibrato` call `__mulint`/`__mulschar` in the ISR, against the
  no-16-bit-multiply rule. Only channels with bend or vibrato active pay for it.
