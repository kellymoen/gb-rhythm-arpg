# 0002 — GBDK-2020 C with our own engine

**Status:** accepted (2026-10-27)

GBDK-2020 4.5.0 (SDCC) in C, with no third-party game framework. Hand-written assembly is allowed only
for hot paths that profiling proves slow (OAM build, metasprite draw, depth sort, VRAM copy).
Logic that doesn't touch hardware lives in `src/core/` as portable C99, so it is unit-tested natively
with clang and could later back a desktop "combat lab" front end.

Rejected: GB Studio (cannot express an isometric renderer or beat-locked combat); pure RGBDS assembly (too
slow to iterate for a feel-driven prototype).
