# Decisions pending the author's confirmation

Design values Claude chose without the author (ADR 0007/0008 process). Each stays **PROVISIONAL** until
the author confirms or overturns it; then move it to "Settled" with the date, or change the value.

## Open

| # | Since | Area | Provisional choice | Where it lives |
|---|-------|------|--------------------|----------------|
| 1 | M2 | Combo strings | **Rush** `A A A A` (fast light chain); **Pause** `A A . A` (rest, then a wide finisher); **Crush** `B . B`, with a forward+B variant that lunges | `data/combos.toml` |
| 2 | M2 | OFFBEAT steps | Still advance the string, but deal `damage >> offbeat_damage_shift`, play no musical hit and use the short hitstop | `data/tuning.toml` `[combat]`, `[hitstop]` |
| 3 | M2 | String break | An unwritten empty step slot ends the string after `string_grace` (1) slots | `data/tuning.toml` `[combat]` |
| 4 | M2 | Training dummy | A stationary dummy with a hurtbox, hit flash and hitstop as the M2 target | `src/scenes/combatflat.c` |
| 5 | M2 | Combat music | Placeholder ~8-bar loop with a `HITS` track and a tempo change 120→140 at bar 5 | `assets/music/combat_genplaceholder.mid` |
| 6 | M2 | Musical-hit pitch | Hit N of the current string plays pitch N of the song's HITS set; a press that breaks a string and starts another plays pitch 0; dodges, ignored presses and OFFBEAT steps play none (chosen by the author 2026-10-29, values still to tune) | `src/scenes/combatflat.c` `schedule_hit`, `src/core/combo.h` `combo_hit` |
| 8 | M2 | Sprite tag data (asset contract) | `hit=<k>` is 1-based within the tag. `dur=<n>/<d>` is a fraction of a whole note: `1/4` = 1 beat, `dur=1` = 4 beats; `loop` marks looping tags; `optional` allows missing facings. Hitboxes come from a `hitbox:<tag>` slice (or per-frame `hitbox` keys) and exist only on the hit frame | `docs/sprites.md` |
| 9 | M2 | Placeholder anim timings | Attacks 1/8 (finisher and heavies 1/4), idle 1/2 loop, walk 1/4 loop, dodge and hurt 1/8 | `assets/sprites/player_genplaceholder.aseprite` |
| 10 | M2 | Combo details | Attacks jab1–4, wide, smash1–2, lunge with damage 2/2/2/3/8/4/7/7 and lunge 4/4/4/6/8/2/4/24 px. A plain step accepts any held direction; a direction variant wins only when its direction is held. A second press on a slot already taken does nothing. A dodge ends the string. A string may not be the start of a longer one. `unlock` is stored but not enforced | `data/combos.toml`, `src/core/combo.c` |
| 11 | M2 | Lunge | `combat.lunge_px` is now a cap on per-attack lunge distances | `data/tuning.toml` |
| 12 | M2 | SFX file format (asset contract — please review) | One TOML per effect: `channel`, `priority`, up to 16 `[[step]]` tables. A step with `volume` retriggers the channel, and a step without it changes the running sound. Envelope, length, sweep and wave apply only on trigger steps | `docs/sfx.md` |
| 13 | M2 | SFX channels and priorities | NOISE: swings 4/5, hits 6/7. P1: dodge 6, perfect 10, menu 3/4, calibration click 12 (no longer played by the game: the calibration song is the click; kept as the highest-priority P1 effect the SFX and lab tests use). WAVE: string break 5. P2: musical hits 8 | `assets/sfx/*_genplaceholder.toml` |
| 14 | M2 | Musical hit sound | 10 frames at volume 15. Combat song HITS set: A4 C5 D5 E5 G5 A5 C6 | `data/tuning.toml`, `assets/music/combat_genplaceholder.mid` |
| 15 | M2 | Calibration | 16 taps to a click song (`calib`: 110 BPM 4/4, a short high P1 click on every beat over a closed hat, beat 1 an octave higher and louder; audio only, no visual cue). The median with halves rounded away from zero becomes the offset. Spread is the middle half and never blocks Accept. Musical hits are muted while calibrating | `src/scenes/calibrate.c`, `assets/music/calib_genplaceholder.mid` |
| 16 | M2 | Timing overlay | 1 px per frame over ±15, the last 6 presses, Select toggles it, DEBUG only | `src/gb/overlay.c` |
| 17 | M2 | Lab saves on placeholders | Saving an SFX from the feel lab edits `<name>_genplaceholder.toml` in place, so your tuning stays inside a Claude-named file until you Save As without the suffix. The alternative: the lab saves your edits as `<name>.toml`, making the file yours | `tools/lab/` |
| 7 | M2 | Hitstop / flash / slow-mo amounts | Hitstop 8/5/2 ticks (PERFECT/GOOD/OFFBEAT), flash 6 ticks, slow-mo 2 beats at 1/2 enemy rate | `data/tuning.toml` |
| 18 | M2 | Combat scene layout and movement | Flat isometric floor; the dummy at screen (104, 88), the player starts at (56, 96). The D-pad walks in screen space at `player.walk_speed` 16 (1 px/frame; diagonals 3/4 per axis); the dummy's footprint (`dummy.solid_w/h` 9x5 px) blocks the player; no movement during attacks, dodges or hurt | `src/scenes/combat.h`, `data/tuning.toml` |
| 19 | M2 | Combo direction | The held D-pad relative to facing: within 45 degrees = forward, the opposite 3 directions = back, square = side. While attacking the player does not turn, so forward means "toward where I face" | `src/scenes/combatflat.c` |
| 20 | M2 | Soft lock | An attack turns toward the dummy when it is within `combat.lock_range_px` (40) on both axes and within 45 degrees of the held direction (else the facing); it then slides to contact by the attack's lunge (capped by `lunge_px`), easing out (half the rest every `player.slide_halflife_ticks`, 2 song ticks) and finishing at once on the hit frame. With no target the attack turns to the held direction and does not lunge | `src/scenes/combatflat.c` |
| 21 | M2 | Hits | Screen-space hitbox vs hurtbox overlap, plus feet within `combat.hit_depth_px` (12) on screen y. One hit per attack. Heavy hit sound for B steps and finishers. Hitstop by the step's grade on both characters; the dummy flinches (hurt anim). Counters: total damage, hits in the current string, the finished string's name (or BREAK / DODGE / PERFECT DODGE / OUCH / DODGED!) | `src/scenes/combat_events.c` |
| 22 | M2 | Hit flash | The dummy switches to OBJ palette 1 (DMG OBP1 / CGB palette 1: colours 1-2 white, outline dark) for `hit_flash_ticks` | `src/scenes/combat_ui.c` |
| 23 | M2 | Grade popups | A 16x16 PERFECT / GOOD / OFF word over the player for every A/B press (dodges too), rising 1 px per `feedback.popup_rise_ticks` (8) song ticks for `feedback.popup_ticks` (36) | `src/scenes/combat_ui.c`, `assets/ui/popups_sprites_genplaceholder.png` |
| 24 | M2 | Dodge | A+B plays the dodge anim and dashes `player.dodge_px` (16) in the held direction, else straight back, easing out like the lunge (`player.slide_halflife_ticks`); SFX_DODGE (SFX_PERFECT instead on a perfect dodge). A perfect dodge always starts slow-mo, whether or not anything was dodged | `src/scenes/combatflat.c`, `combat_events.c` |
| 25 | M2 | Slow-mo | The dummy's anim gets every `enemy_divider`-th frame's ticks (half speed); a telegraphed strike still lands on its beat, but no new telegraph starts during slow-mo; when slow-mo ends a looping anim restarts in phase with the song. Cue: background colours 1-3 one shade darker (floor lines stand out), SFX_PERFECT, "PERFECT DODGE" | `src/scenes/combat_events.c`, `src/gb/fx.c` |
| 26 | M2 | Training dummy strike | Every `dummy.attack_every_beats` (16) beats a "!" over the dummy, shown for the first `dummy.telegraph_blink_ticks` (36) ticks of each beat, a strike `telegraph_beats` (2) later on the beat, with a mark and a heavy swing sound. It hurts a player whose feet are within `range_px` (24; y counts double) unless they are dodging or press a dodge judged at most `good_window` frames after the beat (counted in VBlanks by the press's own frame). Being hurt plays the hurt anim, does not break the string and does not lock input | `src/scenes/combat_events.c` |
| 27 | M2 | String break sound | SFX_STRING_BREAK only when a string breaks after `feedback.break_sound_min_hits` (2) or more hits (a lone stray hit breaks silently) | `src/scenes/combat_events.c` |
| 28 | M2 | Musical-hit timing | With `feedback.quantize_hits` (1) a hit sounds on its step slot's beat position: an early press waits for the slot, an on-time or late one plays as soon as it is known. A hit never plays before `input.dodge_grace` frames after its press (a dodge must play none), so on-time and late presses sound 2 frames after the press. One hit is scheduled at a time; a newer one replaces one that has not played | `src/gb/isr.c` |
| 29 | M2 | Menu sounds | SFX_MENU_MOVE on a cursor move, SFX_MENU_SELECT on a pick; the select sound starts with the next scene (the LCD is off while it loads) | `src/scenes/menu.c` |

### Questions raised in M2 (no provisional answer yet)

| # | Since | Area | Question |
|---|-------|------|----------|
| 30 | M2 | Grade windows vs tempo | At 140 BPM an 8th-note slot is about 12.9 frames wide, so no press can be more than 6 frames off. With `good_window` = 6, OFFBEAT is impossible after bar 5. Should the windows scale with the slot length, e.g. as a fraction of it? |
| 31 | M2 | Perfect dodge with nothing to dodge | A PERFECT dodge starts slow-mo even when no strike is coming. Should slow-mo need a strike within range? |
| 32 | M2 | Sprite palettes (deferred) | ADR 0006's `assets/palettes.aseprite` (layers and tags map to palettes) is not implemented. Sprites use one 4-shade palette. Proposed for M4 juice, unless you want it in M3 |
| 33 | M2 | Debug menu in combat | The generated debug menu is in the rhythm test only. In combat, Select toggles the timing overlay, and A/B attack. The feel lab covers combat tuning. Add an in-combat menu in M3? |

## Settled

| Date | Decision |
|------|----------|
| 2026-10-29 | Aseprite `dur=` is the whole tag's length (ADR 0006) |
| 2026-10-29 | SFX are authored as register-level TOML per effect, editable in the feel lab (ADR 0006) |
