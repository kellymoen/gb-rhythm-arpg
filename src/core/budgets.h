#ifndef CORE_BUDGETS_H
#define CORE_BUDGETS_H

/* Hard hardware budgets (ADR 0001), declared once. The engine includes this file; the converters in
 * tools/gbtools parse the `#define BUDGET_<NAME> <int>` lines and fail any asset that does not fit,
 * so keep each one on a single line with a plain integer value. */

/* Characters (8x16 OBJ mode) */
#define BUDGET_PLAYER_W 24          /* px */
#define BUDGET_PLAYER_H 32          /* px */
#define BUDGET_PLAYER_OBJS 6        /* hardware sprites per player frame */
#define BUDGET_ENEMY_W 16           /* px */
#define BUDGET_ENEMY_H 32           /* px */
#define BUDGET_ENEMIES 4            /* on screen at once */
#define BUDGET_OBJS_PER_LINE 10     /* hardware limit per scanline */
#define BUDGET_FRAME_TILES 12       /* 8x8 tiles in one animation frame (one VRAM slot) */
#define BUDGET_STREAM_BYTES 192     /* bytes in one frame's slot. Streaming is time-bounded, not per-frame:
                                     * ~80 B per VBlank plus main-loop slack, so a 12-tile frame shows 1-2
                                     * video frames after it is due (docs/perf.md) */
#define BUDGET_ANIM_FRAMES 16       /* frames per tag (anim_t holds 16 ends) */

/* Background */
#define BUDGET_BG_TILES 180         /* unique 8x8 tiles per arena (ADR 0001: 150-190) */
#define BUDGET_BG_PX 256            /* max arena background width and height */

#endif
