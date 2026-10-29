#include "test.h"
#include "core/beat.h"
#include "tuning.h"

/* 120 BPM at 59.7275 fps: 48 * 2 / 59.7275 = 1.6073 ticks/frame -> 411.5 in 8.8. */
#define RATE_120 411

static void set_timing(int16_t spb, int16_t perfect, int16_t good, int16_t latency)
{
    tuning_reset();
    tuning.timing_steps_per_beat = spb;
    tuning.timing_perfect_window = perfect;
    tuning.timing_good_window = good;
    tuning.timing_latency_offset = latency;
}

static beat_clock_t clock_at(uint16_t beat, uint8_t tick, uint8_t frac)
{
    beat_clock_t c;
    beat_clock_start(&c, RATE_120);
    c.beat = beat;
    c.tick = tick;
    c.frac = frac;
    return c;
}

void test_beat_clock_step(void)
{
    beat_clock_t c;
    unsigned i, total = 0;

    beat_clock_start(&c, 256); /* exactly one tick per frame */
    for (i = 0; i < BEAT_TICKS; i++)
        total += beat_clock_step(&c);
    CHECK_EQ(total, BEAT_TICKS);
    CHECK_EQ(c.beat, 1);
    CHECK_EQ(c.tick, 0);

    /* 120 BPM: 597 frames (~10 s) is very nearly 20 beats. */
    beat_clock_start(&c, RATE_120);
    for (i = 0; i < 597; i++)
        beat_clock_step(&c);
    CHECK_EQ(c.beat, 19);
    CHECK_EQ(c.tick > 40, 1);

    /* Fast tempo: several ticks per frame, crossing the beat boundary mid-step. */
    beat_clock_start(&c, 1024);
    c.tick = 46;
    CHECK_EQ(beat_clock_step(&c), 4);
    CHECK_EQ(c.beat, 1);
    CHECK_EQ(c.tick, 2);
}

void test_beat_judge_grades(void)
{
    beat_clock_t c;
    judgement_t j;

    set_timing(2, 3, 6, 0);

    c = clock_at(4, 0, 0); /* exactly on beat 4 */
    beat_judge(&c, &j);
    CHECK_EQ(j.grade, GRADE_PERFECT);
    CHECK_EQ(j.frames, 0);
    CHECK_EQ(j.slot, 8);

    c = clock_at(4, 24, 0); /* exactly on the off-beat 8th */
    beat_judge(&c, &j);
    CHECK_EQ(j.frames, 0);
    CHECK_EQ(j.slot, 9);

    c = clock_at(4, 5, 0); /* 5 ticks late = 3.1 frames -> 3 */
    beat_judge(&c, &j);
    CHECK_EQ(j.frames, 3);
    CHECK_EQ(j.grade, GRADE_PERFECT);

    c = clock_at(4, 8, 0); /* 8 ticks late = 5 frames */
    beat_judge(&c, &j);
    CHECK_EQ(j.frames, 5);
    CHECK_EQ(j.grade, GRADE_GOOD);

    c = clock_at(3, 40, 0); /* 8 ticks early for beat 4 */
    beat_judge(&c, &j);
    CHECK_EQ(j.frames, -5);
    CHECK_EQ(j.slot, 8);
    CHECK_EQ(j.grade, GRADE_GOOD);

    c = clock_at(4, 12, 0); /* halfway between slots: furthest possible, 7.5 frames */
    beat_judge(&c, &j);
    CHECK_EQ(j.grade, GRADE_OFFBEAT);
}

void test_beat_judge_latency_and_subdivision(void)
{
    beat_clock_t c;
    judgement_t j;

    /* Seen 2 ticks after beat 4, but with 2 frames (~3.2 ticks) of latency the press was early. */
    set_timing(2, 3, 6, 2);
    c = clock_at(4, 2, 0);
    beat_judge(&c, &j);
    CHECK_EQ(j.frames, -1);
    CHECK_EQ(j.slot, 8);

    /* Latency pulls the press back across the previous beat boundary. */
    set_timing(1, 3, 6, 10);
    c = clock_at(4, 1, 0);
    beat_judge(&c, &j);
    CHECK_EQ(j.slot, 4);
    CHECK_EQ(j.frames < 0, 1);

    /* Quarter-note slots: the 8th off-beat is now the worst place to press. */
    set_timing(1, 3, 6, 0);
    c = clock_at(4, 24, 0);
    beat_judge(&c, &j);
    CHECK_EQ(j.grade, GRADE_OFFBEAT);
    tuning_reset();
}

void test_beat_ticks_until_slot(void)
{
    beat_clock_t c;

    set_timing(2, 3, 6, 0);
    c = clock_at(4, 10, 0);
    CHECK_EQ(beat_ticks_until_slot(&c, 9), 14);
    CHECK_EQ(beat_ticks_until_slot(&c, 10), 38);
    CHECK_EQ(beat_ticks_until_slot(&c, 8), 0);
    tuning_reset();
}

/* beat_judge and beat_ticks_until_slot as they were in M1 (16-bit multiplies), kept as the reference the multiply-free version
 * must match exactly. */
static void judge_reference(const beat_clock_t *c, judgement_t *j)
{
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    uint8_t slot_ticks = BEAT_TICKS / spb;
    uint8_t slot_in_beat = 0, tick = c->tick;
    int16_t slot_len = (int16_t)slot_ticks << 8;
    int16_t pos, dist, frames;
    uint16_t slot;

    if (c->rate == 0) {
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
    pos -= tuning.timing_latency_offset * (int16_t)c->rate;
    while (pos < 0) {
        pos += slot_len;
        slot--;
    }
    while (pos >= slot_len) {
        pos -= slot_len;
        slot++;
    }
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

static uint16_t ticks_until_reference(const beat_clock_t *c, uint16_t slot)
{
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    uint8_t slot_ticks = BEAT_TICKS / spb;
    uint16_t now_slot = c->beat * spb + c->tick / slot_ticks;
    uint8_t into = c->tick % slot_ticks;

    if (slot <= now_slot)
        return 0;
    return (uint16_t)(slot - now_slot) * slot_ticks - into;
}

void test_beat_judge_matches_reference(void)
{
    static const int16_t spbs[] = {1, 2, 3, 4, 6, 8};
    static const uint16_t rates[] = {256, 411, 480, 1100};
    static const uint16_t beats[] = {0, 1, 7, 300, 4000};
    unsigned si, ri, bi, mismatches = 0;
    int16_t latency;
    uint8_t tick;

    for (si = 0; si < sizeof spbs / sizeof spbs[0]; si++)
        for (latency = -15; latency <= 15; latency += 5)
            for (ri = 0; ri < sizeof rates / sizeof rates[0]; ri++)
                for (bi = 0; bi < sizeof beats / sizeof beats[0]; bi++)
                    for (tick = 0; tick < BEAT_TICKS; tick++) {
                        beat_clock_t c;
                        judgement_t got, want;
                        set_timing(spbs[si], 3, 6, latency);
                        beat_clock_start(&c, rates[ri]);
                        c.beat = beats[bi];
                        c.tick = tick;
                        c.frac = (uint8_t)(tick * 37);
                        beat_judge(&c, &got);
                        judge_reference(&c, &want);
                        if (beats[bi] == 0 && want.slot > 0x8000)
                            continue; /* latency before song start: both wrap, nobody presses then */
                        if (got.grade != want.grade || got.frames != want.frames || got.slot != want.slot)
                            mismatches++;
                        if (beat_slot_now(&c) != want.slot)
                            mismatches++;
                        if (beat_ticks_until_slot(&c, want.slot + 2) != ticks_until_reference(&c, want.slot + 2))
                            mismatches++;
                    }
    CHECK_EQ(mismatches, 0);
    tuning_reset();
}

void test_beat_slot_now(void)
{
    beat_clock_t c;

    set_timing(2, 3, 6, 0);
    c = clock_at(4, 0, 0);
    CHECK_EQ(beat_slot_now(&c), 8);
    c = clock_at(4, 11, 255); /* still nearer slot 8 */
    CHECK_EQ(beat_slot_now(&c), 8);
    c = clock_at(4, 13, 0); /* past halfway: a press now is judged against slot 9 */
    CHECK_EQ(beat_slot_now(&c), 9);
    c = clock_at(4, 40, 0);
    CHECK_EQ(beat_slot_now(&c), 10);

    set_timing(2, 3, 6, 8); /* 8 frames (~12.9 ticks) of latency pull the nearest slot back */
    c = clock_at(4, 13, 0);
    CHECK_EQ(beat_slot_now(&c), 8);

    beat_clock_start(&c, 0); /* no song: there is no slot */
    CHECK_EQ(beat_slot_now(&c), 0);
    tuning_reset();
}
