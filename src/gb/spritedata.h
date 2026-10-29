#ifndef GB_SPRITEDATA_H
#define GB_SPRITEDATA_H

#include <gbdk/metasprites.h>
#include <stdint.h>

/* Character sprite data layout shared by tools/gbtools/sprites.py and the sprite runtime
 * (src/gb/anim.c, oam.c, vram_stream.c). Keep them in sync, like audio/song.h for music.
 *
 * Asset contract (ADR 0006): one .aseprite per character, tags `<action>_<facing>` for the drawn
 * facings S, SE, E, NE, N. Tag user data `dur=<n>/<d>` is the musical length of the WHOLE tag
 * (dur=1/8 = an 8th note); Aseprite's per-frame durations set how that length is split between
 * frames. `hit=<frame>` marks the frame whose hitbox is live. Slices `pivot` (feet), `hitbox`,
 * `hurtbox`. Mirrored facings SW, W, NW are drawn by flipping SE, E, NE at runtime. */

enum { FACING_S, FACING_SE, FACING_E, FACING_NE, FACING_N, FACING_NW, FACING_W, FACING_SW, FACING_COUNT };
#define DRAWN_FACINGS 5 /* S..N; facing f > FACING_N draws drawn facing (FACING_COUNT - f), flipped */

#define ANIM_LOOP 0x01      /* restart after the last frame (idle, walk) */
#define ANIM_NO_HIT 0xFF    /* sprite_anim_t.hit_frame when the tag has no hit frame */

typedef struct {
    int8_t x, y;   /* top-left, px relative to the pivot */
    uint8_t w, h;  /* w == 0: no box on this frame */
} box_t;

typedef struct {
    const uint8_t *tiles;       /* tile_count * 16 bytes of 2bpp data, in the sprite's ROM bank */
    const metasprite_t *parts;  /* GBDK metasprite: origin = pivot, tile indices relative to the
                                 * frame's VRAM slot, terminated by METASPR_TERM */
    uint8_t tile_count;         /* <= BUDGET_FRAME_TILES; 8x16 parts count as 2 */
    box_t hitbox;
    box_t hurtbox;
} sprite_frame_t;

typedef struct {
    const sprite_frame_t *frames;
    const uint16_t *ends;       /* frame i shows while the anim's song-tick count < ends[i];
                                 * ends[frame_count - 1] is the tag's whole length in song ticks
                                 * (BEAT_TICKS per beat), precomputed so playback needs no division */
    uint8_t frame_count;
    uint8_t hit_frame;          /* or ANIM_NO_HIT */
    uint8_t flags;              /* ANIM_* */
} sprite_anim_t;

typedef struct {
    /* [action * DRAWN_FACINGS + drawn facing]; actions are the generated SPRITE_<NAME>_<ACTION>
     * enum. A missing tag is NULL (the converter only allows that for actions marked optional). */
    const sprite_anim_t *const *anims;
    uint8_t action_count;
    uint8_t bank;               /* ROM bank holding this struct and `anims`. The anims themselves may
                                 * span several banks: the generated sprite_<name>_anim_bank[] gives
                                 * each one's bank (see the generated header) */
} sprite_t;

#endif
