#pragma bank 255

#include <gb/gb.h>
#include <string.h>

#include "gb/spriteanim.h"

/* Banked: everything in ROM (sprite tables, anims, frames) is read through far_copy(), the only
 * part in bank 0. Per-frame paths avoid multiplies: frames are reached by stepping a pointer. */

#define DRAWN(f) ((f) > FACING_N ? (uint8_t)(FACING_COUNT - (f)) : (f))
#define FLIPPED(f) ((f) > FACING_N)

/* Copy n bytes from ROM bank `bank`; returns with the caller's bank mapped again. */
static void far_copy(void *dst, uint8_t bank, const void *src, uint8_t n) NONBANKED
{
    uint8_t saved = CURRENT_BANK;

    SWITCH_ROM(bank);
    memcpy(dst, src, n); /* GBDK's, in bank 0 */
    SWITCH_ROM(saved);
}

/* Read the anim for (action, facing) into *out; returns 0 if the sprite has none. */
static uint8_t lookup(const spriteanim_t *s, uint8_t action, uint8_t facing, sprite_anim_t *out,
                      uint8_t *bank)
{
    const sprite_anim_t *sa;
    uint8_t i = (uint8_t)((action << 2) + action) + DRAWN(facing); /* action * DRAWN_FACINGS */

    if (action >= s->action_count)
        return 0;
    far_copy(&sa, s->bank, &s->anims[i], sizeof sa);
    if (!sa)
        return 0;
    far_copy(bank, s->bank, &s->anim_banks[i], 1);
    far_copy(out, *bank, sa, sizeof *out);
    return 1;
}

/* Copy the anim's ends into anim_t (clamped to ANIM_MAX_FRAMES); returns the frame count to use. */
static uint8_t load_ends(spriteanim_t *s)
{
    uint8_t n = s->sa.frame_count;

    if (n > ANIM_MAX_FRAMES) {
        far_copy(s->anim.ends, s->sa_bank, s->sa.ends, (ANIM_MAX_FRAMES - 1) * 2);
        far_copy(&s->anim.ends[ANIM_MAX_FRAMES - 1], s->sa_bank, &s->sa.ends[n - 1], 2);
        return ANIM_MAX_FRAMES;
    }
    far_copy(s->anim.ends, s->sa_bank, s->sa.ends, (uint8_t)(n << 1));
    return n;
}

/* The frame being looked at (a global: SDCC reaches globals far more cheaply than pointers). */
static sprite_frame_t fr;

static void read_frame(const spriteanim_t *s, uint8_t i)
{
    const sprite_frame_t *f = s->sa.frames;

    for (; i; i--)
        f++;
    far_copy(&fr, s->sa_bank, f, sizeof fr);
}

void spriteanim_init(spriteanim_t *s, const sprite_t *sprite, uint8_t bank,
                     const sprite_bank_t *anim_banks, uint8_t tile, uint8_t slot_tiles) BANKED
{
    sprite_t spr;

    far_copy(&spr, bank, sprite, sizeof spr);
    s->sprite = sprite;
    s->anim_banks = anim_banks;
    s->anims = spr.anims;
    s->action_count = spr.action_count;
    s->bank = bank;
    s->tile = tile;
    s->slot_tiles = slot_tiles;
    s->playing = 0;
    s->late = 0;
    s->action = 0;
    s->facing = FACING_S;
    s->events = 0;
    s->hitbox.w = 0;
    s->hurtbox.w = 0;
    s->front = 0;
    memset(s->slot, 0, sizeof s->slot);
    s->slot[0].look.parts = s->slot[0].parts;
    s->slot[1].look.parts = s->slot[1].parts;
    s->slot[0].look.tile = tile;
    s->slot[1].look.tile = tile + slot_tiles;
    s->draw.look = s->slot[0].look;
    s->anim.quiet = 0;
    vram_stream_add(&s->job);
}

uint8_t spriteanim_play(spriteanim_t *s, uint8_t action, uint8_t facing, const beat_clock_t *now) BANKED
{
    sprite_anim_t sa;
    uint8_t bank, n;
    uint16_t start = 0;

    if (!lookup(s, action, facing, &sa, &bank))
        return 0;
    s->sa = sa;
    s->sa_bank = bank;
    n = load_ends(s);
    if ((sa.flags & ANIM_LOOP) && now)
        start = anim_loop_phase(now, s->anim.ends[n - 1]);
    anim_play(&s->anim, s->anim.ends, n, sa.hit_frame, sa.flags, start);
    s->playing = 1;
    s->action = action;
    s->facing = facing;
    s->hitbox.w = 0;
    return 1;
}

uint8_t spriteanim_face(spriteanim_t *s, uint8_t facing) BANKED
{
    sprite_anim_t sa;
    uint8_t bank, n;

    if (facing == s->facing)
        return 1;
    if (!s->playing || DRAWN(facing) == DRAWN(s->facing)) {
        /* same art, mirrored or not: the slots just flip */
        s->facing = facing;
        s->slot[0].look.flip = s->slot[1].look.flip = s->draw.look.flip = FLIPPED(facing) ? S_FLIPX : 0;
        return 1;
    }
    if (!lookup(s, s->action, facing, &sa, &bank))
        return 0;
    s->sa = sa;
    s->sa_bank = bank;
    n = load_ends(s);
    anim_retarget(&s->anim, s->anim.ends, n, sa.hit_frame, sa.flags);
    s->facing = facing;
    if (s->anim.mframe == s->anim.hit_frame) {
        read_frame(s, s->anim.hit_frame);
        s->hitbox = fr.hitbox;
    }
    return 1;
}

/* The visible frame changed: get its parts and tiles into a slot. */
static void show_frame(spriteanim_t *s)
{
    const uint8_t *src = fr.tiles;
    uint8_t bank = s->sa_bank, k, n;
    vram_job_t *j = &s->job;
    sprite_slot_t *fs, *bs, *t;

    if (s->front) {
        fs = &s->slot[1];
        bs = &s->slot[0];
    } else {
        fs = &s->slot[0];
        bs = &s->slot[1];
    }
    s->hurtbox = fr.hurtbox;
    if (j->state == VJ_COPYING)
        bs->src = 0; /* abandoning a half-copied slot */
    if (src == fs->src && bank == fs->bank) {
        /* already on screen (frames that share tiles): new parts and flip only */
        j->state = VJ_IDLE;
        t = fs;
    } else {
        t = bs;
        if (src == bs->src && bank == bs->bank) {
            /* the hidden slot still holds it: 2-frame loops stop streaming after one cycle */
            j->state = VJ_READY;
        } else {
            n = fr.tile_count;
            if (n > s->slot_tiles)
                n = s->slot_tiles;
            bs->src = src; /* trusted once the job is READY; nothing shows it before */
            bs->bank = bank;
            vram_stream_submit(j, bank, src, bs->look.tile, n);
        }
    }
    /* each part is an 8x16 OBJ = 2 tiles, so tile_count says how many parts there are */
    k = fr.tile_count >> 1;
    if (k > OAM_MAX_PARTS)
        k = OAM_MAX_PARTS;
    t->look.count = k;
    t->look.flip = FLIPPED(s->facing) ? S_FLIPX : 0;
    if (k) {
        far_copy(t->parts, bank, fr.parts, k << 2);
        /* the converter emits parts row by row, top first */
        t->look.top = t->parts[0].dy;
        t->look.bottom = t->parts[k - 1].dy + 16;
    }
    /* an upper bound on OBJs per row: a 12-tile slot is 3 OBJs wide at most, an 8-tile one 2 */
    n = s->slot_tiles >> 2;
    t->look.per_row = n < k ? n : k;
    if (t == fs)
        s->draw.look = t->look;
}

uint8_t spriteanim_presents = 0xFF;

uint8_t spriteanim_step(spriteanim_t *s, uint8_t ticks) BANKED
{
    uint8_t ev;

    if (!s->playing)
        return s->events = 0;
    ev = anim_advance(&s->anim, ticks);
    if (ev & ANIM_EV_HIT) {
        read_frame(s, s->anim.hit_frame);
        s->hitbox = fr.hitbox;
    }
    if ((ev & ANIM_EV_FRAME) || s->late) {
        if (spriteanim_presents) {
            spriteanim_presents--;
            s->late = 0;
            read_frame(s, s->anim.frame);
            show_frame(s);
        } else {
            s->late = 1;
            s->anim.quiet = 0; /* try again next frame */
        }
    }
    return s->events = ev;
}

void spriteanim_swap(spriteanim_t *s) BANKED
{
    s->front ^= 1;
    s->job.state = VJ_IDLE;
    s->draw.look = s->slot[s->front].look;
}

static void mirror(const box_t *b, uint8_t flip, box_t *out)
{
    *out = *b;
    if (flip)
        out->x = (int8_t)(-(b->x + (int8_t)b->w));
}

uint8_t spriteanim_hitbox(const spriteanim_t *s, box_t *out) BANKED
{
    mirror(&s->hitbox, FLIPPED(s->facing), out);
    return s->playing && s->hitbox.w && s->anim.mframe == s->anim.hit_frame;
}

void spriteanim_hurtbox(const spriteanim_t *s, box_t *out) BANKED
{
    mirror(&s->hurtbox, FLIPPED(s->facing), out);
}
