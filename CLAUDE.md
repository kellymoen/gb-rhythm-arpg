# Beat ARPG (working title)

Isometric rhythm-combat action RPG for Game Boy / Game Boy Color, built with GBDK-2020 4.5.0 in C.
The current goal is the **vertical slice**, whose only job is to prove that combat feels good on real
hardware. Architecture decisions live in `docs/adr/`; domain terms in `CONTEXT.md` — use them.

## Commands
- `make` — build `build/beatarpg.gbc` (dual-mode, MBC5 + battery RAM)
- `make DMG=1` — DMG-only header (test greyscale mode on a GBC)
- `make DEBUG=1` — debug symbols (`.cdb` for Emulicious) + debug menu
- `make test` — host C unit tests (clang) + converter tests (pytest) + ROM tests (headless PyBoy:
  golden screenshots, sound, frame budget). `UPDATE_GOLDEN=1 make test-rom` re-records goldens — review them.
- `make run` / `make emu` — open the ROM in SameBoy / Emulicious; `make listen` — render ROM audio to a WAV
- `make placeholders` — write missing placeholder assets (never overwrites)
- `GBDK_HOME` defaults to `~/opt/gbdk`

## Layout
- `src/core/` — portable C99 game logic. **Never include GBDK headers here**; it is compiled both
  for the ROM and natively for `tests/host/`.
- `src/gb/` — platform code (VRAM, OAM, interrupts, input). `src/audio/` — sound driver.
  `src/scenes/` — one file per scene.
- `assets/` — author-owned sources (`.aseprite`, `.tmx`, `.mid`). `data/*.toml` — gameplay data.
- `tools/gbtools/` — Python converters (run via `uv`). Output goes to `build/gen/` — never edit it.

## Rules
- The DMG sets every budget. Do not use CGB double speed, HDMA or VRAM bank 1 for anything
  except CGB tile attributes/palettes (ADR 0001).
- Musical time comes only from the beat clock (ADR 0004). Never time combat in raw frames.
- Feel values are tuning params in `data/tuning.toml`, not literals in C.
- Converters must validate input and fail with a message that names the file, element and fix.
- Placeholder assets must follow the asset contract exactly (ADR 0006) so the author can replace them.
- Per-frame and ISR code: no 32-bit math and no 16-bit multiply/divide/modulo (SDCC helpers cost
  hundreds to thousands of cycles). Step values incrementally or use subtraction loops. See `docs/perf.md`.
- Update sprites/palettes first after `vsync()`; BG text is slow with the LCD on, so spread it across
  frames. `tests/rom` fails if the main loop ever misses a frame.
- The main loop reads the beat clock only through `music_now()` (the ISR can fire mid-read).
