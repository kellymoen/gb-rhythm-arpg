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
4. **Flashcart** — EZ-Flash Junior or EverDrive GB X7 for testing on your Game Boy Color.

## Composing in Logic Pro
Use four monophonic tracks named `P1`, `P2`, `WAVE`, `NOISE` (plus an optional `HITS` track listing the
pitches combo hits may use). Export MIDI into `assets/music/`. Full convention: `docs/adr/0005-*`.
