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

- `symbol` is looked up in the DEBUG ROM's `.noi` file. A top-level `source` may name a directory when
  every field carries its own `source`; a top-level `"layout": {...}` object is informational.
- `path` is the key path into the source TOML. Integers index arrays of tables, e.g.
  `["string", 0, "steps", 1]`.
- `type` is one of `i8`, `u8`, `i16`, `u16` or `enum`. An `enum` field adds
  `"values": {"A": 1, "B": 2, ...}`, is stored as a `u8`, may give its `default` as a name, and
  takes its range from `values`, so it needs no `min`/`max`.
- Saving rewrites only the edited values and keeps the TOML's comments and layout. The lab passes the
  saver only fields whose value differs from `default`, and after a save the saved values become the new
  defaults (the ROM's compiled-in defaults change on the next build).
- The ROM reads its tables every frame, so a poke takes effect at once. A field that needs
  re-initialising says so with `"restart": true`.

**Optional field keys** (in addition to `path offset type default min max doc values restart`):

| key | meaning |
|-----|---------|
| `source` | The TOML file this field is saved into, relative to the repo root. Default: the descriptor's top-level `source`. Needed when one RAM table spans many files (one per sound effect). A field is identified by `(source, path)`, so two files may both have a `["priority"]`; the same pair twice is an error. The UI groups a table's fields by source (one collapsible block per file, with its own Save and Reset). |
| `step` | Slider granularity, an integer >= 1 (default 1). The slider counts from `min`, so `min 7, max 15, step 8` offers 7 and 15 only. |
| `none` | An "unset" sentinel *outside* `min..max` and inside the type's range (e.g. `255`, or `65535` for a `u16`); not valid on enums (put the sentinel in `values`). The field may hold it (`default` may be it) and the lab may write it to WRAM. It means the key is absent from the TOML: the UI shows an explicit "unset" toggle; saving it **deletes the key**, and saving a real value where the key is missing **adds it**. |
| `absent` | The key or array slot is not in the TOML yet. Saving adds it (padding arrays with the default) only once the value differs from `default`. A key the TOML leaves out without being marked (an implicit converter default) is treated the same way; a missing *parent* table is an error (the descriptor is stale). |
| `array_length` | On a numeric field whose `path` ends in the key of an array of tables (e.g. `["step"]`): the value is how many elements are in use. UI rows of elements at or past it are hidden. Saving a larger value **appends empty tables** to the array and a smaller one **drops the tail** (edits to dropped elements are ignored). `max` is how many elements the ROM has room for. |
| `restart` | See above. |

**Slots the descriptor does not list.** A converter lists the elements its TOML has (and may list more
with `absent`). If the descriptor also carries `"layout": {"step_size": N}` (the byte stride of one array
element), the lab synthesises the rest up to the `array_length` field's `max`: element 0's fields cloned at
that stride, marked `absent`, with empty-slot defaults (the `none` sentinel where there is one, else the
enum's `0` value or the range's floor). They are offered in the UI once the length reaches them, and
raising the length gives all-zero slots those defaults so the ROM never plays `frames = 0`. Saving writes a
key of a new element only if the author moved it off its empty default. Element 0 is therefore the
template and must list every key (the sound converter's first step always triggers, which does).

`layout` is otherwise informational (record sizes for tools that address unlisted bytes).

**Enum and string values.** An enum is written to the TOML by name when the TOML holds a string, by number
otherwise. A numeric value replaces a string where the file had one (`pitch = "A4"` becomes `pitch = 1985`,
keeping the comment); the lab only touches fields the author changed, so untouched note names stay.

**Validation before writing.** A converter may let the lab vet a candidate file: for tables the lab knows
(`sfx`, `combos`) the candidate is run through the converter's own parser first, and if it would reject it
(say, a trigger-only key left on a step whose `volume` was unset) nothing is written and the converter's
message is shown instead.

Over the slice the lab grows from timing and audio (M2) to combo patterns (M2), enemy AI (M3) and
VFX (M4). The author also intends to push GB sound design hard, so the sound driver stays data-driven,
with room for live instrument editing.

The DEBUG ROM also exports `_press_log` / `_press_log_head` (`src/gb/input.h`): a ring of the last 16
judged presses (frame, buttons, grade, frame error) for the lab's graphs.
