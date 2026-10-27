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
  emulator / display / audio lag. Zero on real hardware.

## Combat
- **Step** — one element of a combo string: a button (`A` light, `B` heavy) with an optional
  direction modifier, or a **rest** (a deliberately empty step slot).
- **String** — an ordered sequence of steps that produces a named combo, e.g. `A A . A`.
  Strings carry an `unlock` field for later RPG progression.
- **Dodge** — `A+B` pressed together within `dodge_grace` frames.
- **Perfect dodge** — a dodge graded `PERFECT`; the only thing that triggers **slow-mo**.
- **Slow-mo** — state where enemies update at a reduced rate; music and the beat clock continue.
- **Telegraph** — an enemy wind-up that starts on one beat and strikes on a later beat.
- **Attack token** — permission to attack; only 1–2 enemies hold one at a time.
- **Soft lock** — an attack turns toward the nearest enemy in the held direction (or the last
  target) and **lunges** up to `lunge_px`.
- **Musical hit** — a combo-hit sound played with the song's hit instrument at a pitch from the
  song's `HITS` pitch set, quantized to the beat.

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
- **Placeholder** — Claude-generated asset meant to be painted over / replaced by the author.
- **Tuning param** — a feel value from `data/tuning.toml`, mutable at runtime via the debug menu.
