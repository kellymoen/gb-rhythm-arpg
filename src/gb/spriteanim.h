#ifndef GB_SPRITEANIM_H
#define GB_SPRITEANIM_H

#include <gb/gb.h>
#include <stdint.h>

#include "core/anim.h"
#include "core/beat.h"
#include "gb/oam.h"
#include "gb/spritedata.h"
#include "gb/vram_stream.h"

/* One character on screen: a generated sprite (gb/spritedata.h) playing a beat-relative anim
 * (core/anim.h), its tiles streamed into two VRAM slots (gb/vram_stream.h) and drawn depth-sorted
 * (gb/oam.h).
 *
 * Main loop, once per frame (spriteanim_* for every character):
 *   music_now(&now); ticks = anim_clock_ticks(&clock, &now);
 *   ev = spriteanim_update(s, ticks);              anim events: ANIM_EV_FRAME / _HIT / _DONE
 *   spriteanim_play() / _face() / _hitstop()       as the game decides
 *   oam_begin(); spriteanim_draw(s, x, y, depth)...; oam_end();
 *   ... the rest of the frame's work ...
 *   if (vram_stream_update(deadline_ly) && LY_REG < limit_ly) {
 *       spriteanim_show_ready(s)...; oam_end();
 *   }
 * Tiles only go into the slot that is not on screen; a slot is shown only after its copy finished;
 * the slot just hidden is not overwritten before the next VBlank's OAM DMA (copies happen at the end
 * of a frame, after that frame's swaps). A frame whose tiles finish streaming in the same main-loop
 * pass appears on screen at the next VBlank.
 *
 * Plays made after this frame's spriteanim_update() show from the next frame's update on, which
 * spreads the cost of starting an anim and of showing its first frame over two frames.
 *
 * Calls are expensive with SDCC; pass the address of a global (`&player`) to the macros so the
 * fields are addressed directly. */

/* Same as the generated sprite_<name>.h (proposed for gb/spritedata.h). */
#ifndef GEN_SPRITE_BANK_T
#define GEN_SPRITE_BANK_T
typedef struct { uint8_t bank; } sprite_bank_t;
#endif

/* One of a character's two VRAM slots. */
typedef struct {
    const uint8_t *src;                /* the ROM tiles it holds (0 = none, or half copied) */
    uint8_t bank;
    oam_look_t look;                   /* what its frame draws */
    metasprite_t parts[OAM_MAX_PARTS];
} sprite_slot_t;

typedef struct {
    /* set by spriteanim_init */
    const sprite_t *sprite;            /* in ROM bank `bank` */
    const sprite_bank_t *anim_banks;
    const sprite_anim_t *const *anims; /* sprite_t.anims, read once */
    uint8_t action_count;
    uint8_t bank;
    uint8_t tile;                      /* slot 0's first VRAM tile; slot 1 follows (even bases) */
    uint8_t slot_tiles;

    /* the anim */
    anim_t anim;
    uint8_t action, facing;            /* SPRITE_<NAME>_<ACTION>, FACING_* */
    sprite_anim_t sa;                  /* RAM copy; its pointers are into ROM bank `sa_bank` */
    uint8_t sa_bank;
    uint8_t playing;
    uint8_t late;                      /* a frame change waits for spriteanim_presents */
    uint8_t events;                    /* ANIM_EV_* from the last update */
    box_t hitbox, hurtbox;             /* hit frame's hitbox; shown frame's hurtbox (unmirrored) */

    /* the two VRAM slots */
    vram_job_t job;                    /* fills slot front ^ 1 */
    uint8_t front;
    sprite_slot_t slot[2];
    oam_draw_t draw;                   /* what is drawn: position + the front slot's look */
} spriteanim_t;

/* Set up a character and register its stream job (call at scene start, after vram_stream_reset()
 * and in priority order: the player first). Slots: tiles `tile` .. tile + 2 * slot_tiles - 1. */
void spriteanim_init(spriteanim_t *s, const sprite_t *sprite, uint8_t bank,
                     const sprite_bank_t *anim_banks, uint8_t tile, uint8_t slot_tiles) BANKED;
#define SPRITEANIM_INIT(s, name, tile, slot_tiles) \
    spriteanim_init((s), &sprite_##name, BANK(sprite_##name), sprite_##name##_anim_bank, (tile), (slot_tiles))

/* Start `action` facing `facing`. Loops start in phase with the song (`now`); one-shots start at
 * their first frame. Returns 0, changing nothing, when the sprite has no such anim (optional actions,
 * missing facings). */
uint8_t spriteanim_play(spriteanim_t *s, uint8_t action, uint8_t facing, const beat_clock_t *now) BANKED;

/* Turn to `facing`, keeping the anim's musical position (and hitstop). Returns 0 if the new facing's
 * anim is missing (then nothing changes). */
uint8_t spriteanim_face(spriteanim_t *s, uint8_t facing) BANKED;

/* Freeze the visible frame for `ticks` song ticks; the anim then catches up to the beat. */
#define spriteanim_hitstop(s, ticks) anim_hitstop(&(s)->anim, (ticks))

/* Advance by song ticks; queue a new frame's tiles. Returns ANIM_EV_* (also kept in events). Frames
 * with nothing to report cost no call.
 *
 * Showing a new frame costs ~15 scanlines (SDCC), so at most spriteanim_presents characters do it per
 * video frame; the caller refills it every frame (update the player first). A character over budget
 * shows its frame a video frame later; its anim, events and boxes stay on the beat. */
extern uint8_t spriteanim_presents;
#define spriteanim_update(s, ticks) \
    (ANIM_ADVANCE_QUIET(&(s)->anim, (ticks)) ? ((s)->events = 0) : spriteanim_step((s), (ticks)))
uint8_t spriteanim_step(spriteanim_t *s, uint8_t ticks) BANKED;

/* Between oam_begin() and oam_end(): show a frame whose tiles finished streaming, then add the
 * character at screen pivot (x, y) with iso depth `depth`. */
#define spriteanim_draw(s, px, py, pdepth)          \
    do {                                            \
        spriteanim_show_ready(s);                   \
        (s)->draw.x = (px);                         \
        (s)->draw.y = (py);                         \
        oam_add(&(s)->draw, (pdepth));              \
    } while (0)

/* Swap in a slot whose copy finished. After a late vram_stream_update(), call oam_end() again. */
#define spriteanim_show_ready(s)                    \
    do {                                            \
        if ((s)->job.state == VJ_READY)             \
            spriteanim_swap(s);                     \
    } while (0)
void spriteanim_swap(spriteanim_t *s) BANKED;

/* Boxes in screen px relative to the pivot, mirrored for SW/W/NW. The hitbox is live (returns 1)
 * while the anim is musically on its hit frame. */
uint8_t spriteanim_hitbox(const spriteanim_t *s, box_t *out) BANKED;
void spriteanim_hurtbox(const spriteanim_t *s, box_t *out) BANKED;

#endif
