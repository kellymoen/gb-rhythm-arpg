# 0008 — Feel is tuned in emulation, with a feel lab

**Status:** accepted (2026-10-29)

Real-hardware timing is out of scope for the vertical slice; feel is judged in emulation. **SameBoy** is
the reference emulator for playtesting and its latency offset is the default in `data/tuning.toml`;
Emulicious is for debugging. Latency is the player's to dial in: a **calibration screen** ships in the
release ROM (tap A to a click, median error becomes the latency offset, saved to battery SRAM) and a
**timing overlay** (recent press errors against the grade windows) exists in DEBUG builds.

**Feel lab** (`tools/lab/`): runs the DEBUG ROM in PyBoy and serves a local web UI. It edits tunable
tables live in WRAM, saves them straight back to their TOML source, records and replays input, and
graphs every press with its grade and frame error. Recorded replays double as ROM regression tests. The
in-ROM debug menu remains the fallback that works in any emulator.

**Lab descriptors.** Anything the lab can tune lives in a RAM table in DEBUG builds. The converter that
generates the table also writes `build/gen/<table>.lab.json`:

```json
{
  "source": "data/tuning.toml",
  "symbol": "_tuning",
  "fields": [
    { "path": ["timing", "perfect_window"], "offset": 0, "type": "i16",
      "default": 3, "min": 0, "max": 10, "doc": "+/- frames around a step slot that grade PERFECT" }
  ]
}
```

- `symbol` is looked up in the DEBUG ROM's `.noi` file.
- `path` is the key path into the source TOML. Integers index arrays of tables, e.g.
  `["string", 0, "steps", 1]`.
- `type` is one of `i8`, `u8`, `i16`, `u16` or `enum`. An `enum` field adds
  `"values": {"A": 1, "B": 2, ...}` and is stored as a `u8`.
- Saving rewrites only the edited values and keeps the TOML's comments and layout.
- The ROM reads its tables every frame, so a poke takes effect at once. A field that needs
  re-initialising says so with `"restart": true`.

Over the slice the lab grows from timing and audio (M2) to combo patterns (M2), enemy AI (M3) and
VFX (M4). The author also intends to push GB sound design hard, so the sound driver stays data-driven,
with room for live instrument editing.

The DEBUG ROM also exports `_press_log` / `_press_log_head` (`src/gb/input.h`): a ring of the last 16
judged presses (frame, buttons, grade, frame error) for the lab's graphs.
