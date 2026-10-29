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
| 6 | M2 | Musical-hit pitch | Hit N of the current string plays pitch N of the song's HITS set; resets when the string ends (chosen by the author 2026-10-29, values still to tune) | `src/audio/sfx.h` `sfx_hit_step` |
| 8 | M2 | Sprite tag data (asset contract) | `hit=<k>` is 1-based within the tag. `dur=<n>/<d>` is a fraction of a whole note: `1/4` = 1 beat, `dur=1` = 4 beats; `loop` marks looping tags; `optional` allows missing facings. Hitboxes come from a `hitbox:<tag>` slice (or per-frame `hitbox` keys) and exist only on the hit frame | `docs/sprites.md` |
| 9 | M2 | Placeholder anim timings | Attacks 1/8 (finisher and heavies 1/4), idle 1/2 loop, walk 1/4 loop, dodge and hurt 1/8 | `assets/sprites/player_genplaceholder.aseprite` |
| 10 | M2 | Combo details | Attacks jab1–4, wide, smash1–2, lunge with damage 2/2/2/3/8/4/7/7 and lunge 4/4/4/6/8/2/4/24 px. A plain step accepts any held direction; a direction variant wins only when its direction is held. A second press on a slot already taken does nothing. A dodge ends the string. A string may not be the start of a longer one. `unlock` is stored but not enforced | `data/combos.toml`, `src/core/combo.c` |
| 11 | M2 | Lunge | `combat.lunge_px` is now a cap on per-attack lunge distances | `data/tuning.toml` |
| 12 | M2 | SFX file format (asset contract — please review) | One TOML per effect: `channel`, `priority`, up to 16 `[[step]]` tables. A step with `volume` retriggers the channel, and a step without it changes the running sound. Envelope, length, sweep and wave apply only on trigger steps | `docs/sfx.md` |
| 13 | M2 | SFX channels and priorities | NOISE: swings 4/5, hits 6/7. P1: dodge 6, perfect 10, menu 3/4, calibration click 12. WAVE: string break 5. P2: musical hits 8 | `assets/sfx/*_genplaceholder.toml` |
| 14 | M2 | Musical hit sound | 10 frames at volume 15. Combat song HITS set: A4 C5 D5 E5 G5 A5 C6 | `data/tuning.toml`, `assets/music/combat_genplaceholder.mid` |
| 15 | M2 | Calibration | 16 taps on the rhythm-test song's beat (audio only, no visual cue). The median with halves rounded away from zero becomes the offset. Spread is the middle half and never blocks Accept. Musical hits are muted while calibrating | `src/scenes/calibrate.c` |
| 16 | M2 | Timing overlay | 1 px per frame over ±15, the last 6 presses, Select toggles it, DEBUG only | `src/gb/overlay.c` |
| 17 | M2 | Lab saves on placeholders | Saving an SFX from the feel lab edits `<name>_genplaceholder.toml` in place, so your tuning stays inside a Claude-named file until you Save As without the suffix. The alternative: the lab saves your edits as `<name>.toml`, making the file yours | `tools/lab/` |
| 7 | M2 | Hitstop / flash / slow-mo amounts | Hitstop 8/5/2 ticks (PERFECT/GOOD/OFFBEAT), flash 6 ticks, slow-mo 2 beats at 1/2 enemy rate | `data/tuning.toml` |

## Settled

| Date | Decision |
|------|----------|
| 2026-10-29 | Aseprite `dur=` is the whole tag's length (ADR 0006) |
| 2026-10-29 | SFX are authored as register-level TOML per effect, editable in the feel lab (ADR 0006) |
