# The feel lab

Tune game feel with sliders instead of code edits (ADR 0008). The lab runs the **DEBUG ROM** in PyBoy (a
real window you play with the keyboard, with sound) and serves a web page for live tuning, a press/grade
graph, and recording and replaying input.

```
make lab                       # builds the DEBUG ROM + descriptors, opens the window and http://localhost:8750
make lab LABFLAGS="--mute"     # no sound (paced by the clock)
make lab LABFLAGS="--headless --no-browser --port 9000"   # no SDL window; play from the web page's pad
```

Window keys: arrows, **A** = A, **S** = B, **Return** = Start, **Backspace** = Select, **Esc** = quit.
Do not press PyBoy's other hotkeys while recording or replaying (P pause, Z/X save/load state, Space speed,
C palette, comma/period rewind): they change the machine behind the recording's back.

## Live tuning

Every `build/gen/*.lab.json` becomes a section of sliders (`tuning` today; combo patterns and sound tables
follow the same format). Moving a slider writes the value into the ROM's RAM table at once; the ROM reads
its tables every frame, so you feel it on the next beat. Values changed in the ROM's own debug menu show up
in the sliders too (they are polled).

- **Save** (per table) / **Save all** writes the current values back into the source TOML (`data/tuning.toml`)
  and touches only the lines you changed: comments, order and layout stay. The saved values become the
  table's new defaults. The ROM's compiled-in defaults only change when you rebuild (`make`).
- **Reset** (per table / all) and the per-field arrow restore the defaults (the last saved or built values).
- A field marked `restart` needs **Restart ROM** to take effect. Restart reboots the ROM and re-applies your
  slider values.
- Ranges come from the TOML comment `# [min..max] doc`; a slider cannot leave its range.

### Many tables, many files

`make lab` loads every descriptor: `tuning` (the feel numbers), `combos` (every combo string and attack:
patterns, damage, lunge, sound) and `sfx` (every effect, every step). The tuning panel is built for that
size: each table is a collapsible block, a table that spans several files (`sfx`: one per effect) has one
block per file with its own **Save** and **Reset**, and inside a file the fields are grouped by the TOML
table they live in (`step 2`, `string 1 · steps`). The **filter box** matches field names, docs and file
names (`noise_width hit`) and opens what it finds. Array indices are shown 1-based, as the converters say them.

- **unset** (sound effects): a key that may be absent from the TOML (a step's `duty`, `pitch`, `noise_*`)
  has an "unset" checkbox. Checked, the ROM gets the "keep the running value" sentinel and **Save deletes
  the key**; unchecking sets a real value, and saving adds the key back.
- **Step count** (`step`, per effect): the number of steps played. Raise it and new step rows appear, with
  empty-step defaults (1 frame, nothing set); fill in what you want and Save appends the `[[step]]` tables
  to the effect file, writing only the keys you set. Lowering it hides the extra steps; Save then removes
  them from the file. Trigger keys (envelope, length, sweep) only count on a step that sets `volume`.
- **Pitch** is a raw period. Notes written as `"A4"` stay as written until you move that slider; then
  the file holds the number (the comment stays).
- Before writing, the lab runs the real converter over the result. If it would reject the file (for example
  you unset `volume` on a step that still has an envelope), nothing is written and the converter's message
  appears under the filter box.
- Effects are saved to the file the build uses: `assets/sfx/<name>_genplaceholder.toml` while it is
  Claude's placeholder. Tuning one edits the placeholder in place; to make it yours, *Save As* without the
  suffix (ADR 0007) and rebuild so the lab edits that file.

## Press graph and latency

Every press the ROM judges is plotted (newest at the right) as its frame error from the beat slot: above 0
is late, below is early. The green band is the PERFECT window, amber GOOD (both read live from the sliders),
dots are coloured by grade. The stats are over presses made since the last latency change (a latency change
starts a fresh sample) and **Clear** restarts the sample.

To dial in latency: tap A along with the music in the rhythm test, then read the **mean**. If it is +3f
you are consistently 3 frames late; the lab offers a one-click `latency_offset` change that centres it.
The **spread** (sd) is your consistency and cannot be fixed by latency; if it is wider than the PERFECT
window the window is probably too tight for the song.

The lab's own latency (keyboard, display, audio path) is not SameBoy's or a console's: see
`docs/lab-audio-spike.md`. Use the lab for windows and feel; confirm `latency_offset` with the calibration
screen on the emulator you ship for.

## Record and replay

1. **Record from boot** restarts the ROM at frame 0 and records every key you press and every slider change
   until you type a name and press **Stop & save**. The file lands in `build/lab/replays/<name>.json`
   (`--replay-dir` to change; copy a good one to `tests/rom/replays/` to turn it into a regression test).
   Release any held keys before starting.
2. **Play** reboots the ROM and replays it in the window, in real time, with sound. Hands off the keyboard.
   When it ends the result is shown (matches / mismatch with the first differences) and your slider values
   come back. Click **Cancel replay** to stop early.
3. **Check headless** replays at full speed in a separate process and reports the same result.

From a terminal: `PYTHONPATH=tools uv run python -m lab replay FILE [--check] [--window] [--mute] [--rom R]`.
`--check` exits 1 on any difference (what a ROM test would run); `--window` watches it with sound.

### Replay file format (version 1)

```json
{
  "format": "beatarpg-replay", "version": 1, "created": "2026-10-29T07:13:01+00:00", "notes": "",
  "rom": {"name": "beatarpg-debug.gbc", "sha1": "..."},
  "model": "cgb",
  "warmup_frames": 120,
  "frames": 552,
  "inputs": [ {"f": 93, "held": ["a"]}, {"f": 108, "held": []} ],
  "pokes":  [ {"f": 0, "symbol": "_tuning", "offset": 6, "type": "i16", "value": -2,
               "path": ["timing", "latency_offset"]} ],
  "expect": {
    "presses": [ {"f": 94, "buttons": ["a"], "grade": "PERFECT", "frames": -1} ],
    "screen_sha1": "766a578d541591ee706a5c5b9689730610cb9116"
  }
}
```

- **Timeline.** Boot the ROM with blank cartridge RAM and run `warmup_frames` ticks with no input (PyBoy's
  boot animation, then the ROM's own init, which sets the tuning tables). That is the main menu and
  **frame 0**. Frame `f` is then the f-th `PyBoy.tick()` after the warm-up (0-based). `frames` is how many
  to run. Render every frame (`pb.tick(1, True, False)`): skipping renders changes later screens.
- **`inputs`** are changes only: from frame `f` on, exactly the listed buttons are held (`right left up down
  a b select start`) until the next entry. Apply them before running tick `f`.
- **`pokes`** write `value` (little-endian, per `type`: `i8 u8 i16 u16 enum`) to RAM at the address of `symbol`
  (from the ROM's `.noi`) plus `offset`, before tick `f`. They hold the sliders that differed from the
  ROM's defaults at frame 0, plus every slider change during the recording. `path` is advisory (the TOML
  key). Pokes make a replay independent of whatever sliders you had set, but not of the ROM's defaults for
  the fields it did not poke: change a default in `data/tuning.toml` and the recording replays the new
  value, which is usually what a regression test wants (re-record when the change is intended).
- **`expect`** is what the ROM did: every judged press (`f` is the tick during which the ROM's press log
  gained it; `buttons`, `grade` OFFBEAT/GOOD/PERFECT, signed `frames` error), and a SHA-1 of the final
  screen (`pb.screen.ndarray.tobytes()`). Either key may be absent; a replay with no `expect` only runs.
  The ROM sha1 is informational: a different build only prints a note.
- **As a ROM test**, read the file, boot `build/ph/beatarpg-debug.gbc` with `ram_file=BytesIO(bytes(131072))`
  (so a leftover `.ram` cannot leak in), tick `warmup_frames`, then replay and compare `expect`. The
  reference implementation is `lab.replay.run_replay(rom, load_replay(path), load_symbols(rom))`, which
  returns `.ok` and `.mismatches`. Replays recorded on placeholder ROMs (`make PLACEHOLDERS=only DEBUG=1`)
  are stable against replacing art.

## Adding tables to the lab

A converter that generates a tunable RAM table also writes `build/gen/<name>.lab.json` (format in ADR 0008:
`source`, `symbol`, `fields[{path, offset, type, default, min, max, doc, values?, restart?}]`), and the
table's symbol must exist in the DEBUG ROM. Nothing else is needed: the lab builds sliders for it, saves
into its `source` TOML (integer path elements index arrays of tables: `["string", 0, "steps", 1]`; an enum's
name is written when the TOML holds a string), and records pokes to it. In `mk/<area>.mk` append the
descriptor to `LAB_JSON` so `make lab` generates it:

```make
LAB_JSON += $(GEN)/combos.lab.json
$(GEN)/combos.lab.json: data/combos.toml tools/gbtools/combos.py
	$(PYTOOLS) gbtools.combos $< $(GEN)
```

The descriptor extensions (`source`, `none`, `step`, `array_length`, `absent`, `layout`) are specified in
ADR 0008. `tuning.lab.json` is written by `tools/gbtools/tuning.py` from the `[min..max] doc` comment on each param.

## Safety and limits

The server listens on 127.0.0.1 only, requires an `X-Lab` header on every change, and rejects other Host
headers, so a web page you have open cannot drive it. Replay names are letters, digits, `-` and `_`.
The lab always starts the ROM with blank cartridge RAM (calibration data saved by another emulator is
never loaded) and never writes a `.ram` file.
