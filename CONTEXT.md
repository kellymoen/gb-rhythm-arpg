# Domain glossary

Use these terms in code, comments, data files and docs. If a new concept appears, add it here.

## Rhythm
- **Beat** — one quarter note of the current song. Counted from song start by the beat clock.
- **Phase** — position inside the current beat, 0..65535 (16-bit fraction).
- **Beat clock** — fixed-point accumulator advanced once per VBlank from the song's tempo map.
  Owned by the sound driver; the single source of musical time for gameplay.
- **Step slot** — a beat subdivision a combo step may land on (8th notes by default:
  `steps_per_beat = 2`).
- **Grade** — how close an input was to the nearest step slot: `PERFECT`, `GOOD`, `OFFBEAT`.
- **Window** — the ±frames that earn a grade (`perfect_window`, `good_window`).
- **Latency offset** — frames subtracted from input time before grading, to compensate for
  emulator / display / audio lag. Zero on real hardware. The default is tuned for SameBoy.
- **Calibration** — the shipped screen where the player taps A on 16 beats of a song and the median
  error becomes their latency offset (saved to battery SRAM).
- **Spread** — the width of the middle half of calibration errors: how steady the taps were.
- **Timing overlay** — DEBUG-only HUD strip plotting recent press errors against the windows.

## Combat
- **Step** — one element of a combo string: a button (`A` light, `B` heavy) with an optional
  direction modifier, or a **rest** (a deliberately empty step slot).
- **String** — an ordered sequence of steps that produces a named combo, e.g. `A A . A`.
  Strings carry an `unlock` field for later RPG progression.
- **Candidate** — a string the steps so far still fit; the matcher keeps every candidate alive until
  the steps diverge.
- **String grace** — how many unwritten empty step slots a string survives before it **breaks**.
- **Attack** — what one step does: animation, damage, hitstop, lunge. Several steps may share one.
- **Dodge** — `A+B` pressed together within `dodge_grace` frames.
- **Perfect dodge** — a dodge graded `PERFECT`; the only thing that triggers **slow-mo**.
- **Slow-mo** — state where enemies update at a reduced rate; music and the beat clock continue.
- **Hitstop** — a short freeze on a hit, in song ticks. Beat-relative animations catch up afterwards
  so they stay on the beat.
- **Hit flash** — the struck target flashing for `hit_flash_ticks`.
- **Training dummy** — the stationary target of the M2 combat scene.
- **Telegraph** — an enemy wind-up that starts on one beat and strikes on a later beat.
- **Attack token** — permission to attack; only 1–2 enemies hold one at a time.
- **Soft lock** — an attack turns toward the nearest enemy in the held direction (or the last
  target) and **lunges** up to `lunge_px`.
- **Musical hit** — a combo-hit sound played with the song's hit instrument: hit N of a string plays
  pitch N of the song's `HITS` set. OFFBEAT presses play none.
- **Sound effect (SFX)** — a register-level effect from `assets/sfx/<name>.toml`, played on one channel.
- **Channel stealing** — an SFX or musical hit takes its channel from the music (or a lower
  **priority** effect); the music keeps time silently there and resumes on its next note.

## World and rendering
- **World coords** — logical ground-plane position in subpixels (16 per pixel), `wx`, `wy`.
- **Screen coords** — pixel position after 2:1 isometric projection.
- **Facing** — one of 8 directions. **Drawn facings** (S, SE, E, NE, N) have art; **mirrored
  facings** (SW, W, NW) are their horizontal flips.
- **Arena** — a self-contained combat room (≤256×256 px background, camera follows player).
- **Field** — the explorable world (deferred past the vertical slice).
- **Budget** — a hard hardware limit (tiles, sprites, bytes per VBlank) declared once and checked
  by both the engine and the asset converters.

## Content
- **Asset contract** — the naming and structure rules a source asset (`.aseprite`, `.tmx`, `.mid`)
  must follow so the build can convert it. Placeholders follow it exactly.
- **Placeholder** — Claude-generated asset meant to be painted over / replaced by the author. Always
  named `<name>_genplaceholder.<ext>`; the author's `<name>.<ext>` replaces it (ADR 0007).
- **Your asset** — any file under `assets/` without the suffix. Agents never write one.
- **Export** — a file the build derives from an asset and commits under `exports/` (e.g. an Aseprite
  sheet), because CI cannot regenerate it.
- **Tuning param** — a feel value from `data/tuning.toml`, mutable at runtime via the debug menu.
- **Feel lab** — host tool (`tools/lab/`) that runs the DEBUG ROM in PyBoy with a web UI for live
  tuning, replay and timing graphs (ADR 0008).
- **Lab descriptor** — `build/gen/<table>.lab.json`: how the lab finds and edits a RAM table and
  where to save it.
- **Provisional** — a design value Claude chose that the author has not confirmed yet; listed in
  `docs/decisions-pending.md`.

## Process
- **Milestone gate** — end of a milestone: ROMs + playtest checklist to the author, who merges the PR.
- **Work package** — one subagent's slice of a milestone, owning a disjoint set of files.
- **Handover** — `docs/handover.md`, written at the end of every orchestrator session for the next.
