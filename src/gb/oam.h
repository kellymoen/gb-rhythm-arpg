#ifndef GB_OAM_H
#define GB_OAM_H

#include <gb/gb.h>
#include <gb/metasprites.h>
#include <stdint.h>

/* World sprites in OAM_WORLD .. OAM_WORLD + OAM_WORLD_COUNT - 1 (gb/video.h), drawn nearest first.
 *
 * Each frame: oam_begin(), oam_add() every visible character (any order), oam_end(). oam_add keeps
 * them sorted by iso depth (insertion sort; larger depth = nearer = lower OAM index, which wins on
 * CGB; on DMG the lower X wins first); oam_end writes the shadow OAM, which GBDK copies to OAM in the
 * next VBlank.
 *
 * A character whose pivot is far enough from the screen edges for any art within the canvas budget
 * (BUDGET_PLAYER_W x BUDGET_PLAYER_H) is copied with 8-bit adds, ~45 M-cycles a part; nearer the
 * edges each part is clipped on its own (~2x slower).
 *
 * Safety net: if the characters' rows could put more than BUDGET_OBJS_PER_LINE OBJs on one
 * scanline, or there are more parts than OAM entries, the write order rotates every frame, so the
 * parts the hardware drops flicker instead of vanishing. */

#define OAM_MAX_PARTS 6 /* BUDGET_PLAYER_OBJS */
#define OAM_MAX_DRAWS 8

/* What a character's current frame draws. */
typedef struct {
    const metasprite_t *parts;   /* in RAM: the converter's items, offsets from the pivot (not
                                  * GBDK's chained deltas), tiles relative to `tile` */
    uint8_t count;               /* parts */
    uint8_t tile;                /* VRAM tile of the frame's slot */
    uint8_t flip;                /* 0 or S_FLIPX: mirror around the pivot */
    int8_t top, bottom;          /* rows covered relative to the pivot (overflow check) */
    uint8_t per_row;             /* most parts on one row, or an upper bound (overflow check) */
} oam_look_t;

typedef struct {
    int16_t x, y;                /* screen px of the pivot */
    oam_look_t look;
} oam_draw_t;

/* oam_begin and oam_add are tiny and in bank 0; oam_end is banked. `depth` is iso_depth() of the
 * pivot. The draw must stay valid until oam_end(). */
void oam_begin(void) NONBANKED;
void oam_add(const oam_draw_t *d, int16_t depth) NONBANKED;
void oam_end(void) BANKED;

/* Frames on which oam_end() had to rotate (safety net), for tests and the debug overlay. */
extern uint8_t oam_overflow_frames;

#endif
