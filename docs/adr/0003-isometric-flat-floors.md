# 0003 — True 2:1 isometric, flat floors, back walls only

**Status:** accepted (2026-10-27)

World logic runs on a ground plane (`wx`, `wy` in 1/16-pixel subpixels) projected to the screen as
`sx = (wx - wy)`, `sy = (wx + wy) / 2`. There is no walkable height. Rooms are open toward the camera:
walls are only at the back, and props block movement but are never tall enough to hide a character
(DMG has no per-tile BG priority — 0001).

The D-pad is screen-aligned: Up moves up the screen, and diagonals follow the isometric grid axes.
Characters have 8 facings: 5 drawn (S, SE, E, NE, N), 3 mirrored. Draw order is a per-frame insertion
sort by depth `wx + wy`.

Maps are authored in Tiled (isometric, 32×16 diamonds). The converter bakes them to deduplicated 8×8 tiles,
takes collision from tile properties, and fails when a map goes over the tile budget.
