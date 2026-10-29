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
void test_combo_rush_on_beat(void);
void test_combo_pause_rest_diverges_from_rush(void);
void test_combo_grace_slots_are_slack(void);
void test_combo_breaks_after_string_grace(void);
void test_combo_written_rest_must_stay_empty(void);
void test_combo_offbeat_steps_still_advance(void);
void test_combo_wrong_button_and_same_slot(void);
void test_combo_direction_variants(void);
void test_combo_dodge_grace(void);
void test_combo_perfect_dodge(void);
void test_combo_tempo_independent(void);
void test_combo_shipped_strings_all_play(void);
void test_combo_table_in_ram(void);
void test_combo_hits(void);
void test_calib(void);
void test_anim_frames_follow_ends(void), test_anim_loops(void), test_anim_tempo_change_keeps_frames_on_the_beat(void), test_anim_one_shot_across_tempo_change(void), test_anim_hitstop_freezes_then_catches_up(void), test_anim_clock_ticks(void), test_anim_loop_phase(void), test_anim_retarget_keeps_position(void), test_anim_long_anims_clamp(void), test_anim_quiet_fast_path_matches(void);

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
    test_combo_rush_on_beat,
    test_combo_pause_rest_diverges_from_rush,
    test_combo_grace_slots_are_slack,
    test_combo_breaks_after_string_grace,
    test_combo_written_rest_must_stay_empty,
    test_combo_offbeat_steps_still_advance,
    test_combo_wrong_button_and_same_slot,
    test_combo_direction_variants,
    test_combo_dodge_grace,
    test_combo_perfect_dodge,
    test_combo_tempo_independent,
    test_combo_shipped_strings_all_play,
    test_combo_table_in_ram,
    test_combo_hits,
    test_calib,
    test_anim_frames_follow_ends, test_anim_loops, test_anim_tempo_change_keeps_frames_on_the_beat, test_anim_one_shot_across_tempo_change, test_anim_hitstop_freezes_then_catches_up, test_anim_clock_ticks, test_anim_loop_phase, test_anim_retarget_keeps_position, test_anim_long_anims_clamp, test_anim_quiet_fast_path_matches,
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
