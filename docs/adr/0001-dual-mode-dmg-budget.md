# 0001 — Dual-mode ROM; the DMG sets every budget

**Status:** accepted (2026-10-27)

The ROM runs on DMG and CGB (header 0x80). It is one game: CGB only adds palettes, via the same 2bpp
tiles plus per-tile CGB palette attributes. We never rely on CGB double speed, HDMA or extra VRAM for
gameplay, animation or content. CPU and VRAM budgets are therefore identical on both machines, so a
Game Boy Color is a valid performance test bench. `make DMG=1` builds a DMG-only header to check
greyscale presentation on the same hardware.

Consequences: about 150–190 unique background tiles per arena; the player is at most 24×32; the CPU copies
one animation frame per VBlank (no HDMA); no BG-over-sprite tile priority, so no occluding foreground
(see 0003). Cartridge: MBC5 + battery SRAM.
