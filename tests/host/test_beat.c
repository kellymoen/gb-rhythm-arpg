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
