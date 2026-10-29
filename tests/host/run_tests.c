#include "test.h"

int test_failures = 0;

void test_iso_project(void);
void test_iso_depth(void);
void test_tuning_defaults(void);
void test_beat_clock_step(void);
void test_beat_judge_grades(void);
void test_beat_judge_latency_and_subdivision(void);
void test_beat_ticks_until_slot(void);
void test_beat_judge_matches_reference(void);
void test_beat_slot_now(void);

static void (*const tests[])(void) = {
    test_iso_project,
    test_iso_depth,
    test_tuning_defaults,
    test_beat_clock_step,
    test_beat_judge_grades,
    test_beat_judge_latency_and_subdivision,
    test_beat_ticks_until_slot,
    test_beat_judge_matches_reference,
    test_beat_slot_now,
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
