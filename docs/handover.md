# Handover

Rewritten by the orchestrator at the end of every session, for the next one. Read with `CLAUDE.md`,
`docs/plan.md` and `docs/decisions-pending.md`.

## State (2026-10-29, M2 in progress)
- **Branch:** `m2-combos` (not pushed yet). **PR:** none yet.
- **Done:** Wave 0, the orchestrator's setup:
  - `_genplaceholder` asset resolution, asset report, `make release` gate and placeholders-only test
    ROMs (ADR 0007).
  - Main menu and scene framework (`src/scenes/scene.h`), with stub combat and calibration scenes.
  - Press frame/held fields and the DEBUG press log.
  - Contracts: `src/core/combo.h`, `src/gb/spritedata.h`, `src/audio/sfx.h`, `src/core/budgets.h`,
    lab descriptors (ADR 0008).
  - New tuning params.
- **Next:** Wave 1a packages (lab, combo matcher, sprite pipeline, audio), then 1b (sprite runtime,
  calibration + overlay), integration, review, gate. The breakdown is in
  `~/.claude/plans/you-are-an-orchestrator-snoopy-iverson.md`.

## Not verified / known gaps
- `BUDGET_STREAM_BYTES` is a guess until the sprite runtime measures VRAM copy cost.

## Gotchas
- `Agent` with `isolation: "worktree"` cuts the worktree from `main`, not from the milestone branch.
  Instead, have each package agent run `git worktree add .claude/worktrees/<pkg> -b <pkg> <milestone
  branch>` itself and work only there.
- Bank 0 holds about 8.6 KB of free space as of Wave 0; bank new code and data.
- A `static` BANKED function crashes: bankpack leaves `b_<fn> = 255` for static symbols. Banked
  functions must be global.
- A song's first VBlank costs `music_update` about 100 scanlines, because every channel starts at
  once. Don't restart a song mid-scene; start it while the LCD is off (in `scene_begin`/`scene_show`).
- ROM tests boot with empty in-memory cartridge RAM (`conftest.boot`). PyBoy would otherwise load
  `<rom>.ram`.
- `UPDATE_GOLDEN=1` re-records every golden that a test asserts. If two tests share a golden name, the
  last one wins, so give each screen its own name.
