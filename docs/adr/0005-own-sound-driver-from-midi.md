# 0005 — Our own sound driver, fed from Logic Pro MIDI

**Status:** accepted (2026-10-27)

The composer works in Logic Pro and auditions with RetroPlug (a real GB emulator as an AU plugin) or
PAPU. Songs are exported as `.mid` into `assets/music/` and converted at build time into compact
per-channel event streams for our own driver.

**MIDI convention**
- Monophonic tracks named `P1`, `P2`, `WAVE`, `NOISE` map to the four APU channels.
- Program change selects an instrument from `assets/music/instruments.toml` (duty, volume envelope,
  wave shape, noise preset).
- CCs adjust duty and volume; pitch bend and vibrato are supported.
- Optional `HITS` track: its pitches form the set used by **musical hits** (combo-hit sounds quantized
  to the beat).
- The tempo map and time signature come from the MIDI file; any BPM and tempo changes are allowed.

Sound effects declare a channel and a priority, steal that channel, and the music resumes afterwards. P2
or NOISE is the conventional interruptible part.

Why: no existing tool chain goes from Logic to the GB with a readable beat position. hUGEDriver hides
its row/tick, and Furnace has no GB export. Owning the driver gives exact beat sync without placing
markers by hand. Fallback if the driver becomes a time sink: Midi2Uge → hUGETracker → a hUGEDriver
patched to export its row.
