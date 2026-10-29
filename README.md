# Beat ARPG (working title)

Isometric rhythm-combat action RPG for Game Boy / Game Boy Color. See `CLAUDE.md` for commands and
`docs/adr/` for the architecture.

## One-time setup (things only you can do)
1. **Aseprite** — built from source (v1.3.18.6, `~/opt/aseprite-src`) and installed as
   `~/Applications/Aseprite.app`. The Makefile finds it there (or on `PATH`); override with `ASEPRITE=`.
   To rebuild after updating the source: `ninja -C ~/opt/aseprite-src/build aseprite`, then copy
   `build/bin/Aseprite.app` over the installed one.
2. **Emulicious** — installed at `~/opt/emulicious` (runs on the Temurin JDK). `make emu` opens the ROM in
   it; use `make emu DEBUG=1` for C source-level debugging. Optionally install VS Code + the
   *Emulicious Debugger* extension.
3. **Logic Pro audition plugins** — RetroPlug (https://github.com/tommitytom/RetroPlug/releases) and/or
   PAPU (https://socalabs.com/synths/papu/).
4. **Flashcart** (optional) — the slice is tuned in SameBoy (ADR 0008); hardware testing comes later.

## Tuning feel
`make lab` opens the game in a window plus a web page of live sliders for every tuning value, a graph of
how early or late your presses are, and input record/replay. **Save** writes straight back to
`data/tuning.toml`. Details: `docs/lab.md`.

## Replacing placeholders
Everything Claude made is named `<name>_genplaceholder.<ext>`. Open it, make it yours, and **Save As**
`<name>.<ext>` in the same folder; the build uses yours from then on. `make` prints
`assets: yours N/M`, and `make release` refuses to build while any placeholder would ship.

## Composing in Logic Pro
Export each song as a MIDI file into `assets/music/<song_name>.mid` (lower_snake_case), then run `make`. To hear
it exactly as the Game Boy plays it, run `make listen` (writes and opens `build/listen.wav`). If something can't be
played, the build stops with a message naming the track, bar and beat.

**Tracks** (names must match; any other track with notes is an error):

| Track   | Plays on | Range | Notes |
|---------|----------|-------|-------|
| `P1`    | pulse 1  | C2–B7 | monophonic |
| `P2`    | pulse 2  | C2–B7 | monophonic; musical hits (on-beat combo hits) briefly take this channel, so give it the part that can drop out |
| `WAVE`  | wave     | C1–B6 | monophonic; output volume has 3 steps (velocity ≥ 96 → 100%, ≥ 43 → 50%, else 25%) |
| `NOISE` | noise    | —     | drum map: each MIDI note picks a `[[drum]]`; note lengths are ignored (drums decay) |
| `HITS`  | (not played) | C2–B7 | the pitches musical hits use, up to 16, lowest first: hit N of a combo string plays the N-th pitch (wrapping), so write a set whose every prefix is a good rising phrase; its program change picks the hit sound |

**Per-track controls:** program change = instrument from `assets/music/instruments.toml` (until you save your own,
the build uses `instruments_genplaceholder.toml`; program 0 if none);
velocity = volume; **CC12** = pulse duty (0–31 12.5%, 32–63 25%, 64–95 50%, 96–127 75%); **CC1** (mod wheel) =
vibrato depth; **pitch bend** = ±2 semitones. Other CCs are ignored. Two notes starting together on one track is
an error (the channels are monophonic).

**Song structure:** tempo changes and the time signature come from the MIDI file. Add a marker named `loop`
where the loop should restart (default: the start) and one named `end` where the song ends (default: the end of
the bar containing the last note).

Audition in Logic with RetroPlug (a real emulated Game Boy as a plugin) or PAPU, using one instance per track
with matching settings.

**Sound effects take channels from the music.** Each effect (`assets/sfx/*.toml`, guide in `docs/sfx.md`) names a
channel. While it plays the music goes silent there, keeps its place, and comes back on its **next note** on that
channel. The placeholders use NOISE for swings and impacts, P1 for dodge, perfect and menu sounds, and WAVE for the
string-break sound. Musical hits use P2. Short notes in those parts recover fastest.

**In the game:** the **RHYTHM TEST** screen plays your songs and effects. **Down** switches between the rhythm-test
song and the combat song (`combat.mid`; BPM shows the live tempo), **Left/Right** pick an effect and **Up** plays it.
Runs of on-beat A/B presses play rising `HITS` pitches the way combo strings will.
