# Handover

Rewritten by the orchestrator at the end of every session, for the next one. Read with `CLAUDE.md`,
`docs/plan.md` and `docs/decisions-pending.md`.

## State (2026-10-29): M2 at the gate
- **Branch:** `m2-combos`, pushed. **PR:** https://github.com/kellymoen/gb-rhythm-arpg/pull/1 → `main`.
  The author merges it after the playtest (their go/no-go for M2).
- **Done:** every M2 package plus the review fixes:
  - wave 0 contracts
  - feel lab
  - combo matcher
  - sprite pipeline
  - SFX, musical hits and the combat song
  - sprite runtime
  - calibration and the timing overlay
  - combat scene
  - an independent standards + spec review, with its findings fixed
- **Tests:** `make test` passes: 34 host, 358 tool and 82 ROM tests. `make release` blocks on placeholders, as designed.
- **Not verified:** nothing has been played by a human or heard by ear. That is the gate.
- **Waiting on the author:** the playtest, then answers on `docs/decisions-pending.md` rows 1–29
  (confirm or change) and 30–33 (open questions). The two asset contracts to review are row 8 (sprite
  tag data) and row 12 (the SFX format).

## Next: M3 Arena (proposed breakdown; the author's "go" approves it)
Design questions to put to the author first:
- **Enemy:** what the first enemy type is and does.
- **Health:** player and enemy health, and what happens at zero.
- **Arena:** size and layout.
- **Soft lock:** how it chooses between several enemies.
- **Open M2 rows:** 30–33.

Waves:
1. **Wave 0 (orchestrator):**
   - Switch the BG VRAM to 0x8800 addressing so an arena gets ~180 BG tiles (ADR 0001; today BG and
     sprites share 0x8000).
   - Tile and OAM budgets in `video.h` for 4 enemies.
   - Contracts: `enemies.toml` schema, the arena map format, an `arena.h` collision API.
2. **Wave 1, in parallel:**
   - **Map pipeline** (Sonnet, tools): Tiled iso `.tmx` → deduplicated 8×8 tiles, collision from tile
     properties, a budget report, and a placeholder arena plus tileset (`_genplaceholder`).
   - **Arena runtime** (Opus): 256×256 BG, camera follow, 8-way iso movement in world coords with
     collision, props in the depth sort.
   - **Enemy** (Opus core + Sonnet placeholder): one enemy type with on-beat telegraphs, attack tokens
     and AI params in `enemies.toml` with a lab descriptor; a 16×32 placeholder sprite.
   - **Perf** (Opus):
     - an assembly `music_update` / `run_event`
     - a faster "show new frame" path in `spriteanim` (OAM-ready part tables from `sprites.py`)
     - `combo` `probe()` in assembly if the combat frame needs it
     - remove the `__mulint` calls in `chan_freq` and `vibrato`
3. **Wave 2 (integration):** an arena scene replacing the flat floor, up to 4 enemies, soft lock across
   enemies, health and damage, the OAM flicker safety net exercised, and replays.

## Known gaps carried into M3
- **Combat input edge case:** `combat_next.heavy` and `combat_pending_held` are set when a press is
  read, not when its event commits. Two presses read in one loop pass, with no tick between them,
  could swap the heavy flag or held direction.
- **SFX unset in the lab:** unsetting a first SFX step's `duty` or `noise_*` key makes the converter
  apply its first-step default, not KEEP. WRAM and the rebuilt ROM then differ for that case.
- **Lab latency:** the lab's latency differs from SameBoy's. Use calibration in SameBoy for the real
  offset.
- **DMG sprite priority:** OBJ priority on DMG goes by X position, so the depth sort only fully holds
  on CGB.
- **Musical-hit floor:** hits play no earlier than `dodge_grace` (2) frames after the press, because a
  B within that time would turn the A into a dodge.

## Gotchas
- **Worktrees:** `Agent` with `isolation: "worktree"` cuts the worktree from `main`, not from the
  milestone branch. Have each package agent run `git worktree add .claude/worktrees/<pkg> -b <pkg>
  <milestone branch>` itself and work only there.
- **Never `git add -A` while agent worktrees exist** unless `.claude/worktrees/` is ignored (it is now).
- **Bank 0** has ~4.3 KB free (release) and ~2.9 KB (DEBUG). Only the ISR and its callees plus
  bank-switching copies live there (CLAUDE.md).
- **Banked functions:** a `static` BANKED function crashes; bankpack leaves `b_<fn> = 255` for static
  symbols.
- **Song start:** a song's first VBlank costs `music_update` about 100 scanlines. Start songs while
  the LCD is off; don't restart one mid-scene.
- **Menu select SFX:** the menu turns the LCD off before queuing its select sound. Starting the
  effect in that VBlank delayed every scene's start by a frame and broke all the replays.
- **Test cartridge RAM:** ROM tests boot with empty in-memory cartridge RAM (`conftest.boot`).
- **Goldens:** `UPDATE_GOLDEN=1` re-records every golden a test asserts. Give each screen its own name.
- **Lab tests:** `tests/tools/test_lab_rom.py` asserts `assets/` and `data/` are clean in git, so
  commit before running `make test` after editing them.
- **Clock reads in PyBoy:** when the LYC=143 stream interrupt delays the VBlank ISR, PyBoy's frame
  boundary can split a clock step. Tests that time presses from `_music_clock` hook
  `beat_clock_step` (see `tests/rom/test_combat.py`).
