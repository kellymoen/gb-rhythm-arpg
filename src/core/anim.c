#ifdef __SDCC
#pragma bank 255
#endif

#include "core/anim.h"

#define ST_START 0x01  /* anim_play ran; the next advance reports the start */
#define ST_END 0x02    /* a one-shot reached its end musically */
#define ST_DONE 0x04   /* ... and ANIM_EV_DONE was reported */
#define ST_REDRAW 0x08 /* anim_retarget ran; the next advance reports a frame change */

/* How many ticks can pass with nothing to report: until the next frame boundary, or 0 while
 * anything is pending (a start, a redraw, a freeze, a finished one-shot). */
static void set_quiet(anim_t *a)
{
    uint16_t left;

    if (a->freeze || (a->state & (ST_START | ST_REDRAW | ST_END))) {
        a->quiet = 0;
        return;
    }
    left = a->ends[a->mframe] - a->pos;
    a->quiet = left > 255 ? 255 : (uint8_t)left;
}

/* Take a new ends table, wrap or clamp the position into it and find the musical frame. */
static void set_table(anim_t *a, const uint16_t *ends, uint8_t n, uint8_t hit_frame, uint8_t flags)
{
    uint16_t len, pos = a->pos;
    uint8_t i, m;

    if (n > ANIM_MAX_FRAMES) {
        a->ends[ANIM_MAX_FRAMES - 1] = ends[n - 1];
        n = ANIM_MAX_FRAMES;
        m = n - 1;
    } else {
        m = n;
    }
    if (ends != a->ends)
        for (i = 0; i < m; i++)
            a->ends[i] = ends[i];
    len = a->ends[n - 1];
    a->frame_count = n;
    a->hit_frame = hit_frame;
    a->flags = flags;
    if (flags & ANIM_LOOP) {
        while (pos >= len)
            pos -= len;
    } else if (pos >= len) {
        pos = len;
        a->state |= ST_END;
    }
    a->pos = pos;
    for (m = 0; m < n - 1 && pos >= a->ends[m]; m++)
        ;
    a->mframe = m;
}

void anim_play(anim_t *a, const uint16_t *ends, uint8_t frame_count, uint8_t hit_frame,
               uint8_t flags, uint16_t start) CORE_BANKED
{
    a->freeze = 0;
    a->state = ST_START;
    a->pos = start;
    set_table(a, ends, frame_count, hit_frame, flags);
    a->frame = a->mframe;
    a->quiet = 0;
}

void anim_retarget(anim_t *a, const uint16_t *ends, uint8_t frame_count, uint8_t hit_frame,
                   uint8_t flags) CORE_BANKED
{
    set_table(a, ends, frame_count, hit_frame, flags);
    if (!a->freeze)
        a->frame = a->mframe;
    else if (a->frame >= a->frame_count)
        a->frame = a->frame_count - 1;
    a->state |= ST_REDRAW;
    a->quiet = 0;
}

uint8_t anim_advance(anim_t *a, uint8_t ticks) CORE_BANKED
{
    const uint16_t *e;
    uint16_t pos;
    uint8_t ev = 0, st = a->state, mf = a->mframe, hit = a->hit_frame;

    if (st & (ST_START | ST_REDRAW)) {
        ev = ANIM_EV_FRAME;
        if ((st & ST_START) && mf == hit)
            ev |= ANIM_EV_HIT;
        st &= (uint8_t)~(ST_START | ST_REDRAW);
    }
    if (!(st & ST_END)) {
        pos = a->pos + ticks;
        e = &a->ends[mf];
        while (pos >= *e) {
            if (mf + 1 < a->frame_count) {
                mf++;
                e++;
                if (mf == hit)
                    ev |= ANIM_EV_HIT;
            } else if (a->flags & ANIM_LOOP) {
                pos -= *e;
                mf = 0;
                e = a->ends;
                if (!hit)
                    ev |= ANIM_EV_HIT;
            } else {
                pos = *e;
                st |= ST_END;
                break;
            }
        }
        a->pos = pos;
        a->mframe = mf;
    }
    if (a->freeze) {
        if (ticks < a->freeze) {
            a->freeze -= ticks;
            a->state = st;
            a->quiet = 0;
            return ev;
        }
        a->freeze = 0;
    }
    if (a->frame != mf) {
        a->frame = mf;
        ev |= ANIM_EV_FRAME;
    }
    if ((st & (ST_END | ST_DONE)) == ST_END) {
        st |= ST_DONE;
        ev |= ANIM_EV_DONE;
    }
    a->state = st;
    set_quiet(a);
    return ev;
}

void anim_hitstop(anim_t *a, uint8_t ticks) CORE_BANKED
{
    if (ticks > a->freeze)
        a->freeze = ticks;
    a->quiet = 0;
}

uint8_t anim_done(const anim_t *a) CORE_BANKED
{
    return (a->state & ST_DONE) != 0;
}

uint16_t anim_loop_phase(const beat_clock_t *now, uint16_t len) CORE_BANKED
{
    uint16_t beats = 0, rest = len, r = 0, b = now->beat;
    uint8_t i, tick = now->tick;

    if (len == 0)
        return 0;
    if (len <= BEAT_TICKS) {
        /* a beat subdivision: only if it divides the beat */
        while (rest < BEAT_TICKS)
            rest += len;
        if (rest != BEAT_TICKS)
            return 0;
        while (tick >= len)
            tick -= (uint8_t)len;
        return tick;
    }
    while (rest >= BEAT_TICKS) {
        rest -= BEAT_TICKS;
        beats++;
    }
    if (rest || beats > 255)
        return 0;
    if (!(beats & (beats - 1))) {
        r = b & (beats - 1); /* a power of two: 1, 2, 4 ... beats */
        return (uint16_t)(r << 5) + (uint16_t)(r << 4) + tick;
    }
    /* beat mod beats, by binary long division (no 16-bit divide helper) */
    for (i = 0; i < 16; i++) {
        r = (uint16_t)(r << 1) | (b >> 15);
        b <<= 1;
        if (r >= beats)
            r -= beats;
    }
    return (uint16_t)(r << 5) + (uint16_t)(r << 4) + tick; /* r * 48 + tick */
}

void anim_clock_sync(anim_clock_t *c, const beat_clock_t *now) CORE_BANKED
{
    c->beat = now->beat;
    c->tick = now->tick;
}

uint8_t anim_clock_ticks(anim_clock_t *c, const beat_clock_t *now) CORE_BANKED
{
    uint16_t beats = now->beat - c->beat;
    int16_t total = (int16_t)now->tick - (int16_t)c->tick;

    c->beat = now->beat;
    c->tick = now->tick;
    if (beats > ANIM_CLOCK_MAX_BEATS)
        return 0; /* went backwards (song restart) or jumped too far */
    while (beats--)
        total += BEAT_TICKS;
    if (total < 0)
        return 0;
    return total > 255 ? 255 : (uint8_t)total;
}
