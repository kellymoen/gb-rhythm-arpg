#include "core/anim.h"

#define ST_START 0x01 /* anim_play ran; the next advance reports the start */
#define ST_END 0x02   /* a one-shot reached its end musically */
#define ST_DONE 0x04  /* ... and ANIM_EV_DONE was reported */

static void seek(anim_t *a)
{
    const uint16_t *ends = a->ends;
    uint8_t last = a->frame_count - 1;

    a->mframe = 0;
    while (a->mframe < last && a->pos >= ends[a->mframe])
        a->mframe++;
}

void anim_play(anim_t *a, const uint16_t *ends, uint8_t frame_count, uint8_t hit_frame,
               uint8_t flags, uint16_t start)
{
    uint16_t len = ends[frame_count - 1];

    a->ends = ends;
    a->len = len;
    a->frame_count = frame_count;
    a->hit_frame = hit_frame;
    a->flags = flags;
    a->freeze = 0;
    a->state = ST_START;
    if (flags & ANIM_LOOP) {
        while (start >= len)
            start -= len;
    } else if (start >= len) {
        start = len;
        a->state |= ST_END;
    }
    a->pos = start;
    seek(a);
    a->frame = a->mframe;
}

uint8_t anim_advance(anim_t *a, uint8_t ticks)
{
    const uint16_t *ends = a->ends;
    uint8_t ev = 0;

    if (a->state & ST_START) {
        a->state &= (uint8_t)~ST_START;
        ev = ANIM_EV_FRAME;
        if (a->mframe == a->hit_frame)
            ev |= ANIM_EV_HIT;
    }
    if (!(a->state & ST_END)) {
        a->pos += ticks;
        while (a->pos >= ends[a->mframe]) {
            if (a->mframe + 1 < a->frame_count) {
                a->mframe++;
                if (a->mframe == a->hit_frame)
                    ev |= ANIM_EV_HIT;
            } else if (a->flags & ANIM_LOOP) {
                a->pos -= a->len;
                a->mframe = 0;
                if (a->hit_frame == 0)
                    ev |= ANIM_EV_HIT;
            } else {
                a->pos = a->len;
                a->state |= ST_END;
                break;
            }
        }
    }
    if (a->freeze) {
        if (ticks < a->freeze) {
            a->freeze -= ticks;
            return ev;
        }
        a->freeze = 0;
    }
    if (a->frame != a->mframe) {
        a->frame = a->mframe;
        ev |= ANIM_EV_FRAME;
    }
    if ((a->state & (ST_END | ST_DONE)) == ST_END) {
        a->state |= ST_DONE;
        ev |= ANIM_EV_DONE;
    }
    return ev;
}

void anim_hitstop(anim_t *a, uint8_t ticks)
{
    if (ticks > a->freeze)
        a->freeze = ticks;
}

uint8_t anim_done(const anim_t *a)
{
    return (a->state & ST_DONE) != 0;
}

uint16_t anim_loop_phase(const beat_clock_t *now, uint16_t len)
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
    /* beat mod beats, by binary long division (no 16-bit divide helper) */
    for (i = 0; i < 16; i++) {
        r = (uint16_t)(r << 1) | (b >> 15);
        b <<= 1;
        if (r >= beats)
            r -= beats;
    }
    return (uint16_t)(r << 5) + (uint16_t)(r << 4) + tick; /* r * 48 + tick */
}

void anim_clock_sync(anim_clock_t *c, const beat_clock_t *now)
{
    c->beat = now->beat;
    c->tick = now->tick;
}

uint8_t anim_clock_ticks(anim_clock_t *c, const beat_clock_t *now)
{
    uint16_t beats = now->beat - c->beat;
    int16_t total = (int16_t)now->tick - (int16_t)c->tick;

    anim_clock_sync(c, now);
    if (beats > ANIM_CLOCK_MAX_BEATS)
        return 0; /* went backwards (song restart) or jumped too far */
    while (beats--)
        total += BEAT_TICKS;
    if (total < 0)
        return 0;
    return total > 255 ? 255 : (uint8_t)total;
}
