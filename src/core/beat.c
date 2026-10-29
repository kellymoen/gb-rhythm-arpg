#include "core/beat.h"
#include "tuning.h"

void beat_clock_start(beat_clock_t *c, uint16_t rate)
{
    c->beat = 0;
    c->tick = 0;
    c->frac = 0;
    c->rate = rate;
}

uint8_t beat_clock_step(beat_clock_t *c)
{
    uint16_t sub = (uint16_t)c->frac + c->rate;
    uint8_t ticks = (uint8_t)(sub >> 8);
    uint8_t t = c->tick + ticks;

    c->frac = (uint8_t)sub;
    while (t >= BEAT_TICKS) {
        t -= BEAT_TICKS;
        c->beat++;
    }
    c->tick = t;
    return ticks;
}

/* BEAT_TICKS / steps_per_beat for steps_per_beat 0..8 (the tuning range is 1..8), so per-frame code
 * needs no divide. 0 maps to a whole beat instead of dividing by zero. */
static const uint8_t slot_ticks_for[9] = {48, 48, 24, 16, 12, 9, 8, 6, 6};

static uint8_t slot_ticks_now(void)
{
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    return spb <= 8 ? slot_ticks_for[spb] : (uint8_t)(BEAT_TICKS / spb);
}

/* a * b by shift-and-add. b is small here (steps_per_beat <= 8, |latency| <= 15), so this is a few
 * 16-bit adds instead of SDCC's multiply helper. */
static uint16_t mul_small(uint16_t a, uint8_t b)
{
    uint16_t r = 0;

    while (b) {
        if (b & 1)
            r += a;
        a <<= 1;
        b >>= 1;
    }
    return r;
}

/* Find the step slot at or before the clock's position minus the latency offset: stores it in *slot
 * and returns how far past it that position is, 0 <= pos < slot_len (8.8 ticks). */
static int16_t locate(const beat_clock_t *c, uint8_t slot_ticks, uint16_t *slot)
{
    uint8_t slot_in_beat = 0, tick = c->tick;
    int16_t slot_len = (int16_t)slot_ticks << 8;
    int16_t latency = tuning.timing_latency_offset;
    int16_t pos;
    uint16_t s;

    while (tick >= slot_ticks) {
        tick -= slot_ticks;
        slot_in_beat++;
    }
    s = mul_small(c->beat, (uint8_t)tuning.timing_steps_per_beat) + slot_in_beat;
    pos = ((int16_t)tick << 8) + c->frac;

    /* The press happened `latency_offset` frames before we saw it. */
    if (latency >= 0)
        pos -= (int16_t)mul_small(c->rate, (uint8_t)latency);
    else
        pos += (int16_t)mul_small(c->rate, (uint8_t)-latency);
    while (pos < 0) {
        pos += slot_len;
        s--;
    }
    while (pos >= slot_len) {
        pos -= slot_len;
        s++;
    }
    *slot = s;
    return pos;
}

/* Runs in the VBlank ISR on every press, so it stays in 16-bit adds and shifts with no multiply or
 * divide: SDCC's helpers cost most of a frame. Ranges: slot_len <= 12288,
 * |latency * rate| <= 15 * ~1100. */
void beat_judge(const beat_clock_t *c, judgement_t *j)
{
    uint8_t slot_ticks = slot_ticks_now();
    int16_t half = (int16_t)((uint16_t)slot_ticks << 7);
    int16_t pos, dist, frames;
    uint16_t slot;

    if (c->rate == 0) { /* no song playing: there is no beat to be on */
        j->grade = GRADE_OFFBEAT;
        j->frames = 0;
        j->slot = 0;
        return;
    }
    pos = locate(c, slot_ticks, &slot);

    /* Distance to the nearer slot edge, rounded to whole frames. */
    if (pos <= half) {
        dist = pos;
    } else {
        dist = (int16_t)((uint16_t)slot_ticks << 8) - pos;
        slot++;
    }
    dist += c->rate >> 1;
    for (frames = 0; dist >= (int16_t)c->rate; frames++)
        dist -= c->rate;
    if (pos > half)
        frames = -frames;

    j->frames = (int8_t)frames;
    j->slot = slot;
    if (frames < 0)
        frames = -frames;
    if (frames <= tuning.timing_perfect_window)
        j->grade = GRADE_PERFECT;
    else if (frames <= tuning.timing_good_window)
        j->grade = GRADE_GOOD;
    else
        j->grade = GRADE_OFFBEAT;
}

uint16_t beat_slot_now(const beat_clock_t *c)
{
    uint8_t slot_ticks = slot_ticks_now();
    uint16_t slot;

    if (c->rate == 0)
        return 0;
    if (locate(c, slot_ticks, &slot) > (int16_t)((uint16_t)slot_ticks << 7))
        slot++;
    return slot;
}

uint16_t beat_ticks_until_slot(const beat_clock_t *c, uint16_t slot)
{
    uint8_t slot_ticks = slot_ticks_now();
    uint8_t into = c->tick, slot_in_beat = 0;
    uint16_t now_slot;

    while (into >= slot_ticks) {
        into -= slot_ticks;
        slot_in_beat++;
    }
    now_slot = mul_small(c->beat, (uint8_t)tuning.timing_steps_per_beat) + slot_in_beat;
    if (slot <= now_slot)
        return 0;
    return mul_small(slot - now_slot, slot_ticks) - into;
}
