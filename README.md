# Beat ARPG (working title)

Isometric rhythm-combat action RPG for Game Boy / Game Boy Color. See `CLAUDE.md` for commands and
`docs/adr/` for the architecture.

## One-time setup (things only you can do)
1. **Aseprite** — build from source (https://github.com/aseprite/aseprite/blob/main/INSTALL.md) and put
   the `aseprite` binary on your `PATH` (the build calls it in batch mode).
2. **Emulicious** — download from https://emulicious.net/downloads/ (needs the Temurin JDK, installed
   via Homebrew). Optionally install VS Code + the *Emulicious Debugger* extension for C debugging.
3. **Logic Pro audition plugins** — RetroPlug (https://github.com/tommitytom/RetroPlug/releases) and/or
   PAPU (https://socalabs.com/synths/papu/).
4. **Flashcart** — EZ-Flash Junior or EverDrive GB X7 for testing on your Game Boy Color.

## Composing in Logic Pro
Use four monophonic tracks named `P1`, `P2`, `WAVE`, `NOISE` (plus an optional `HITS` track listing the
pitches combo hits may use). Export MIDI into `assets/music/`. Full convention: `docs/adr/0005-*`.
