#include "test.h"

int test_failures = 0;

void test_iso_project(void);
void test_iso_depth(void);
void test_tuning_defaults(void);
void test_beat_clock_step(void);
void test_beat_judge_grades(void);
void test_beat_judge_latency_and_subdivision(void);
void test_beat_ticks_until_slot(void);
void test_anim_frames_follow_ends(void), test_anim_loops(void), test_anim_tempo_change_keeps_frames_on_the_beat(void), test_anim_one_shot_across_tempo_change(void), test_anim_hitstop_freezes_then_catches_up(void), test_anim_clock_ticks(void), test_anim_loop_phase(void);

static void (*const tests[])(void) = {
    test_iso_project,
    test_iso_depth,
    test_tuning_defaults,
    test_beat_clock_step,
    test_beat_judge_grades,
    test_beat_judge_latency_and_subdivision,
    test_beat_ticks_until_slot,
    test_anim_frames_follow_ends, test_anim_loops, test_anim_tempo_change_keeps_frames_on_the_beat, test_anim_one_shot_across_tempo_change, test_anim_hitstop_freezes_then_catches_up, test_anim_clock_ticks, test_anim_loop_phase,
};

int main(void)
{
    unsigned i, n = sizeof tests / sizeof tests[0];
    for (i = 0; i < n; i++)
        tests[i]();
    if (test_failures) {
        fprintf(stderr, "%d check(s) failed\n", test_failures);
        return 1;
    }
    printf("%u host tests passed\n", n);
    return 0;
}
