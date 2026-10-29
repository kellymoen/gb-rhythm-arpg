#include <stddef.h>
#include <string.h>

#include "test.h"
#include "combos.h"
#include "core/combo.h"
#include "tuning.h"

/* Rule tests run against a fixture table so the author can change data/combos.toml freely; the last
 * tests check the shipped table plays. Fixture attacks are numbered so events are easy to read. */
#define A_ COMBO_A
#define B_ COMBO_B
#define R_ COMBO_STEP_REST
#define FB (COMBO_B | (COMBO_DIR_FWD << COMBO_STEP_DIR_SHIFT))
#define NA COMBO_NO_ATTACK

enum { RUSH, PAUSE, CRUSH, CRUSH_F, FIXTURES };

static const combo_string_t fixtures[FIXTURES] = {
    {{A_, A_, A_, A_}, {0, 1, 2, 3, NA, NA, NA, NA}, 0},     /* A A A A */
    {{A_, A_, R_, A_}, {0, 1, NA, 4, NA, NA, NA, NA}, 0},    /* A A . A */
    {{B_, R_, B_}, {5, NA, 6, NA, NA, NA, NA, NA}, 0},       /* B . B */
    {{B_, R_, FB}, {5, NA, 7, NA, NA, NA, NA, NA}, 0},       /* B . fB */
};

static combo_t c;
static combo_event_t ev[COMBO_MAX_EVENTS];
static uint8_t frame;

static void setup(int16_t string_grace, int16_t dodge_grace)
{
    tuning_reset();
    tuning.timing_steps_per_beat = 2; /* clock_on() */
    tuning.timing_latency_offset = 0;
    tuning.combat_string_grace = string_grace;
    tuning.input_dodge_grace = dodge_grace;
    combo_reset_with(&c, fixtures, FIXTURES);
    frame = 0;
}

/* Press `buttons` (holding `dir`) judged against `slot`, 10 frames after the previous call. */
static uint8_t press_dir(uint8_t buttons, uint8_t dir, uint16_t slot, grade_t grade)
{
    combo_input_t in;

    frame += 10;
    in.buttons = buttons;
    in.dir = dir;
    in.frame = frame;
    in.judgement.grade = grade;
    in.judgement.frames = 0;
    in.judgement.slot = slot;
    return combo_press(&c, &in, ev);
}

static uint8_t press(uint8_t buttons, uint16_t slot)
{
    return press_dir(buttons, COMBO_DIR_NONE, slot, GRADE_PERFECT);
}

/* A beat clock exactly on step slot `slot` (fixture tests run at 2 slots per beat, no latency). */
static beat_clock_t clock_on(uint16_t slot)
{
    beat_clock_t k;

    beat_clock_start(&k, 411);
    k.beat = slot >> 1;
    k.tick = (slot & 1) ? BEAT_TICKS / 2 : 0;
    return k;
}

static uint8_t tick_at(uint16_t slot, uint8_t at_frame)
{
    beat_clock_t k = clock_on(slot);
    return combo_tick(&c, &k, at_frame, ev);
}

static uint8_t tick(uint16_t slot)
{
    return tick_at(slot, frame);
}

#define CHECK_EV(i, type_, string_, step_, attack_)  \
    do {                                              \
        CHECK_EQ(ev[i].type, type_);                  \
        CHECK_EQ(ev[i].string, string_);              \
        CHECK_EQ(ev[i].step, step_);                  \
        CHECK_EQ(ev[i].attack, attack_);              \
    } while (0)

void test_combo_rush_on_beat(void)
{
    setup(1, 0);
    CHECK_EQ(press(A_, 10), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 0, 0);
    CHECK_EQ(ev[0].grade, GRADE_PERFECT);
    CHECK_EQ(press(A_, 11), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 1, 1);
    CHECK_EQ(tick(12), 0);
    CHECK_EQ(press(A_, 12), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 2, 2); /* Pause died: its rest was pressed */
    CHECK_EQ(press(A_, 13), 1);
    CHECK_EV(0, COMBO_EV_FINISH, RUSH, 3, 3);

    /* A finished string is over: the next press starts a new one at hit 0. */
    CHECK_EQ(press(A_, 14), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 0, 0);
}

void test_combo_pause_rest_diverges_from_rush(void)
{
    setup(1, 0);
    press(A_, 10);
    press(A_, 11);
    CHECK_EQ(tick(12), 0);
    CHECK_EQ(tick(13), 0);
    /* Slot 12 empty: the rest of A A . A fits exactly, Rush would need a grace slot. Pause wins and
     * the finisher is its third hit (rests don't count). */
    CHECK_EQ(press(A_, 13), 1);
    CHECK_EV(0, COMBO_EV_FINISH, PAUSE, 2, 4);
}

void test_combo_grace_slots_are_slack(void)
{
    setup(1, 0);
    press(A_, 10);
    /* One unwritten empty slot is forgiven: still both Rush and Pause, hit 1. */
    CHECK_EQ(press(A_, 12), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 1, 1);
    /* Pause: rest (13) + one grace slot (14) before its finisher. */
    CHECK_EQ(press(A_, 15), 1);
    CHECK_EV(0, COMBO_EV_FINISH, PAUSE, 2, 4);

    /* Rush at half speed: every gap uses the one grace slot. */
    setup(1, 0);
    press(A_, 10);
    press(A_, 12);
    press(A_, 13); /* gap 0 after A A: Rush only */
    CHECK_EQ(press(A_, 15), 1);
    CHECK_EV(0, COMBO_EV_FINISH, RUSH, 3, 3);
}

void test_combo_breaks_after_string_grace(void)
{
    setup(1, 0);
    press(B_, 10);
    /* B . B: slot 11 is the rest, 12 the next hit, 13 the one grace slot. */
    CHECK_EQ(tick(11), 0);
    CHECK_EQ(tick(12), 0);
    CHECK_EQ(tick(13), 0);
    CHECK_EQ(tick(14), 1);
    CHECK_EV(0, COMBO_EV_BREAK, CRUSH, 1, NA);
    CHECK_EQ(tick(15), 0); /* idle now: nothing more to break */

    /* After A A the latest candidate is Pause (its rest buys one more slot). */
    setup(1, 0);
    press(A_, 10);
    press(A_, 11);
    CHECK_EQ(tick(14), 0);
    CHECK_EQ(tick(15), 1);
    CHECK_EV(0, COMBO_EV_BREAK, RUSH, 2, NA);

    /* string_grace 0: no slack at all. */
    setup(0, 0);
    press(A_, 10);
    CHECK_EQ(tick(11), 0);
    CHECK_EQ(tick(12), 1);
    CHECK_EQ(ev[0].type, COMBO_EV_BREAK);
    setup(0, 0);
    press(A_, 10);
    CHECK_EQ(press(A_, 12), 2); /* one empty slot: break, and the press starts a new string */
    CHECK_EV(0, COMBO_EV_BREAK, RUSH, 1, NA);
    CHECK_EV(1, COMBO_EV_STEP, RUSH, 0, 0);

    /* string_grace 2 */
    setup(2, 0);
    press(B_, 10);
    CHECK_EQ(press(B_, 14), 1); /* rest + 2 grace slots */
    CHECK_EV(0, COMBO_EV_FINISH, CRUSH, 1, 6);
}

void test_combo_written_rest_must_stay_empty(void)
{
    setup(1, 0);
    press(B_, 10);
    CHECK_EQ(press(B_, 11), 2);
    CHECK_EV(0, COMBO_EV_BREAK, CRUSH, 1, NA);
    CHECK_EV(1, COMBO_EV_STEP, CRUSH, 0, 5);
    CHECK_EQ(press(B_, 13), 1); /* the restarted string goes on from slot 11 */
    CHECK_EV(0, COMBO_EV_FINISH, CRUSH, 1, 6);
}

void test_combo_offbeat_steps_still_advance(void)
{
    setup(1, 0);
    press_dir(A_, COMBO_DIR_NONE, 10, GRADE_GOOD);
    CHECK_EQ(ev[0].grade, GRADE_GOOD);
    press_dir(A_, COMBO_DIR_NONE, 11, GRADE_OFFBEAT);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 1, 1);
    CHECK_EQ(ev[0].grade, GRADE_OFFBEAT);
    press_dir(A_, COMBO_DIR_NONE, 12, GRADE_PERFECT);
    CHECK_EQ(press_dir(A_, COMBO_DIR_NONE, 13, GRADE_OFFBEAT), 1);
    CHECK_EV(0, COMBO_EV_FINISH, RUSH, 3, 3);
    CHECK_EQ(ev[0].grade, GRADE_OFFBEAT);
}

void test_combo_wrong_button_and_same_slot(void)
{
    setup(1, 0);
    press(A_, 10);
    /* A second press judged against the slot already taken is ignored. */
    CHECK_EQ(press(A_, 10), 0);
    CHECK_EQ(press(A_, 9), 0);
    CHECK_EQ(press(A_, 11), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 1, 1);
    /* B fits no candidate: the string breaks and B starts Crush. */
    CHECK_EQ(press(B_, 12), 2);
    CHECK_EV(0, COMBO_EV_BREAK, RUSH, 2, NA);
    CHECK_EV(1, COMBO_EV_STEP, CRUSH, 0, 5);
}

void test_combo_direction_variants(void)
{
    setup(1, 0);
    press_dir(B_, COMBO_DIR_FWD, 10, GRADE_PERFECT); /* a plain B step takes any direction */
    CHECK_EV(0, COMBO_EV_STEP, CRUSH, 0, 5);
    CHECK_EQ(press_dir(B_, COMBO_DIR_FWD, 12, GRADE_PERFECT), 1);
    CHECK_EV(0, COMBO_EV_FINISH, CRUSH_F, 1, 7); /* the forward variant wins over plain B */

    setup(1, 0);
    press(B_, 10);
    CHECK_EQ(press(B_, 12), 1);
    CHECK_EV(0, COMBO_EV_FINISH, CRUSH, 1, 6);

    setup(1, 0);
    press(B_, 10);
    CHECK_EQ(press_dir(B_, COMBO_DIR_BACK, 12, GRADE_PERFECT), 1); /* no back variant: plain */
    CHECK_EV(0, COMBO_EV_FINISH, CRUSH, 1, 6);
}

void test_combo_dodge_grace(void)
{
    combo_input_t in;

    setup(1, 2);
    /* A lone press is held back for dodge_grace frames... */
    frame = 50;
    in.buttons = A_;
    in.dir = COMBO_DIR_NONE;
    in.frame = 50;
    in.judgement.grade = GRADE_PERFECT;
    in.judgement.frames = 0;
    in.judgement.slot = 10;
    CHECK_EQ(combo_press(&c, &in, ev), 0);
    CHECK_EQ(tick_at(10, 50), 0);
    CHECK_EQ(tick_at(10, 51), 0);
    /* ...and lands once B can no longer pair with it. */
    CHECK_EQ(tick_at(10, 52), 1);
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 0, 0);
    CHECK_EQ(ev[0].grade, GRADE_PERFECT);

    /* B two frames after A: a dodge graded like the earlier press. */
    in.frame = 60;
    in.judgement.slot = 12;
    in.judgement.grade = GRADE_GOOD;
    CHECK_EQ(combo_press(&c, &in, ev), 0);
    in.buttons = B_;
    in.frame = 62;
    in.judgement.grade = GRADE_PERFECT;
    CHECK_EQ(combo_press(&c, &in, ev), 2); /* the dodge ends the string it interrupted */
    CHECK_EV(0, COMBO_EV_BREAK, RUSH, 1, NA);
    CHECK_EV(1, COMBO_EV_DODGE, COMBO_IDLE, 0, NA);
    CHECK_EQ(ev[1].grade, GRADE_GOOD);
    CHECK_EQ(tick_at(12, 70), 0); /* nothing left held back */

    /* Three frames apart: two attacks. */
    in.buttons = A_;
    in.frame = 80;
    in.judgement.slot = 20;
    CHECK_EQ(combo_press(&c, &in, ev), 0);
    in.buttons = B_;
    in.frame = 83;
    in.judgement.slot = 21;
    CHECK_EQ(combo_press(&c, &in, ev), 1); /* A lands; B is held back in turn */
    CHECK_EV(0, COMBO_EV_STEP, RUSH, 0, 0);
    CHECK_EQ(tick_at(21, 85), 2);
    CHECK_EV(0, COMBO_EV_BREAK, RUSH, 1, NA);
    CHECK_EV(1, COMBO_EV_STEP, CRUSH, 0, 5);

    /* A held-back press keeps its string alive past the deadline until it resolves. */
    setup(1, 2);
    in.buttons = B_;
    in.frame = 10;
    in.judgement.slot = 10;
    combo_press(&c, &in, ev);
    tick_at(10, 12);
    in.frame = 20;
    in.judgement.slot = 13; /* rest + grace: the last slot that continues */
    CHECK_EQ(combo_press(&c, &in, ev), 0);
    CHECK_EQ(tick_at(14, 21), 0);
    CHECK_EQ(tick_at(14, 22), 1);
    CHECK_EV(0, COMBO_EV_FINISH, CRUSH, 1, 6);
}

void test_combo_perfect_dodge(void)
{
    setup(1, 2);
    /* A and B on the same frame, idle: just the dodge, with the press's own grade. */
    CHECK_EQ(press_dir(A_ | B_, COMBO_DIR_NONE, 10, GRADE_PERFECT), 1);
    CHECK_EV(0, COMBO_EV_DODGE, COMBO_IDLE, 0, NA);
    CHECK_EQ(ev[0].grade, GRADE_PERFECT);
    CHECK_EQ(press_dir(A_ | B_, COMBO_DIR_NONE, 12, GRADE_OFFBEAT), 1);
    CHECK_EQ(ev[0].grade, GRADE_OFFBEAT);

    /* dodge_grace 0: A then B a frame later are two attacks, and attacks land at once. */
    setup(1, 0);
    CHECK_EQ(press(A_, 10), 1);
    CHECK_EQ(ev[0].type, COMBO_EV_STEP);
}

/* --- tempo independence: a real beat clock at two tempos, pressed on the nearest PERFECT frame --- */

#define TEMPO_SLOTS 20
#define TEMPO_EVENTS 16

static uint8_t play(uint16_t rate, const uint8_t pattern[TEMPO_SLOTS], combo_event_t log[TEMPO_EVENTS])
{
    beat_clock_t clk;
    judgement_t j;
    combo_input_t in;
    uint8_t pressed[TEMPO_SLOTS] = {0};
    uint8_t logged = 0, n, i;
    unsigned f;

    setup(1, 2);
    beat_clock_start(&clk, rate);
    for (f = 0; f < 1500; f++) {
        beat_clock_step(&clk);
        frame++;
        beat_judge(&clk, &j);
        CHECK_EQ(beat_slot_now(&clk), j.slot);
        n = 0;
        if (j.slot < TEMPO_SLOTS && pattern[j.slot] && !pressed[j.slot] && j.frames >= 0) {
            pressed[j.slot] = 1;
            in.buttons = pattern[j.slot];
            in.dir = COMBO_DIR_NONE;
            in.frame = frame;
            in.judgement = j;
            n = combo_press(&c, &in, ev);
        }
        for (i = 0; i < n && logged < TEMPO_EVENTS; i++)
            log[logged++] = ev[i];
        n = combo_tick(&c, &clk, frame, ev);
        for (i = 0; i < n && logged < TEMPO_EVENTS; i++)
            log[logged++] = ev[i];
    }
    return logged;
}

void test_combo_tempo_independent(void)
{
    /* Pause, a pause long enough to break, then Rush with one slack slot, then Crush left hanging. */
    static const uint8_t pattern[TEMPO_SLOTS] = {
        0, 0, A_, A_, 0, A_, 0, 0, A_, A_, 0, 0, 0, 0, A_, 0, A_, A_, A_, B_,
    };
    combo_event_t slow[TEMPO_EVENTS], fast[TEMPO_EVENTS];
    uint8_t n_slow = play(411, pattern, slow);  /* 120 BPM */
    uint8_t n_fast = play(1100, pattern, fast); /* ~321 BPM */
    uint8_t i;

    CHECK_EQ(n_slow, 12);
    CHECK_EQ(n_fast, n_slow);
    for (i = 0; i < n_slow && i < n_fast; i++) {
        CHECK_EQ(fast[i].type, slow[i].type);
        CHECK_EQ(fast[i].string, slow[i].string);
        CHECK_EQ(fast[i].step, slow[i].step);
        CHECK_EQ(fast[i].attack, slow[i].attack);
    }
    CHECK_EQ(slow[2].type, COMBO_EV_FINISH);
    CHECK_EQ(slow[2].string, PAUSE);
    CHECK_EQ(slow[5].type, COMBO_EV_BREAK); /* A A at 8-9, then four empty slots */
    CHECK_EQ(slow[9].type, COMBO_EV_FINISH);
    CHECK_EQ(slow[9].string, RUSH);
    CHECK_EQ(slow[10].type, COMBO_EV_STEP); /* B starts Crush, which then breaks */
    CHECK_EQ(slow[10].string, CRUSH);
    CHECK_EQ(slow[11].type, COMBO_EV_BREAK);
    tuning_reset();
}

/* --- the shipped table ------------------------------------------------------------------------ */

void test_combo_shipped_strings_all_play(void)
{
    uint8_t s, k, n = 0;
    uint16_t slot;

    combos_reset();
    for (s = 0; s < COMBO_STRING_COUNT; s++) {
        const combo_string_t *str = &combos.strings[s];
        tuning_reset();
        tuning.input_dodge_grace = 0;
        combo_reset(&c);
        slot = 100;
        for (k = 0; k < COMBO_MAX_STEPS && str->steps[k] != COMBO_STEP_END; k++, slot++) {
            if (str->steps[k] == COMBO_STEP_REST)
                continue;
            n = press_dir(str->steps[k] & COMBO_STEP_BUTTONS, str->steps[k] >> COMBO_STEP_DIR_SHIFT, slot,
                          GRADE_PERFECT);
            CHECK_EQ(n, 1);
            CHECK_EQ(ev[0].attack, str->attacks[k]);
        }
        CHECK_EQ(ev[0].type, COMBO_EV_FINISH);
        CHECK_EQ(ev[0].string, s);
    }
    tuning_reset();
}

void test_combo_table_in_ram(void)
{
    CHECK_EQ(sizeof(combo_string_t), COMBO_STRING_SIZE);
    CHECK_EQ(sizeof(combo_attack_t), COMBO_ATTACK_SIZE);
    CHECK_EQ(offsetof(combos_t, attacks), COMBO_STRING_COUNT * COMBO_STRING_SIZE);

    /* The lab pokes the RAM copy; the matcher reads it on the next press; reset restores it. */
    combos_reset();
    combos.strings[0].steps[0] = COMBO_B;
    tuning_reset();
    tuning.input_dodge_grace = 0;
    combo_reset(&c);
    press(B_, 10);
    CHECK_EQ(ev[0].string, 0);
    combos_reset();
    CHECK_EQ(memcmp(&combos, &combos_defaults, sizeof combos), 0);
    tuning_reset();
}
