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

/* Runs in the VBlank ISR on every press, so it stays in 16-bit math with no division beyond one
 * 8-bit divide: SDCC's 32-bit helpers cost most of a frame. Ranges: slot_len <= 12288,
 * |latency * rate| <= 15 * ~1100. */
void beat_judge(const beat_clock_t *c, judgement_t *j)
{
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    uint8_t slot_ticks = BEAT_TICKS / spb;
    uint8_t slot_in_beat = 0, tick = c->tick;
    int16_t slot_len = (int16_t)slot_ticks << 8;
    int16_t pos, dist, frames;
    uint16_t slot;

    if (c->rate == 0) { /* no song playing: there is no beat to be on */
        j->grade = GRADE_OFFBEAT;
        j->frames = 0;
        j->slot = 0;
        return;
    }

    while (tick >= slot_ticks) {
        tick -= slot_ticks;
        slot_in_beat++;
    }
    slot = c->beat * spb + slot_in_beat;
    pos = ((int16_t)tick << 8) + c->frac;

    /* The press happened `latency_offset` frames before we saw it. */
    pos -= tuning.timing_latency_offset * (int16_t)c->rate;
    while (pos < 0) {
        pos += slot_len;
        slot--;
    }
    while (pos >= slot_len) {
        pos -= slot_len;
        slot++;
    }

    /* Distance to the nearer slot edge, rounded to whole frames. */
    if (pos <= slot_len / 2) {
        dist = pos;
    } else {
        dist = slot_len - pos;
        slot++;
    }
    dist += c->rate >> 1;
    for (frames = 0; dist >= (int16_t)c->rate; frames++)
        dist -= c->rate;
    if (pos > slot_len / 2)
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

uint16_t beat_ticks_until_slot(const beat_clock_t *c, uint16_t slot)
{
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    uint8_t slot_ticks = BEAT_TICKS / spb;
    uint16_t now_slot = c->beat * spb + c->tick / slot_ticks;
    uint8_t into = c->tick % slot_ticks;

    if (slot <= now_slot)
        return 0;
    return (uint16_t)(slot - now_slot) * slot_ticks - into;
}
