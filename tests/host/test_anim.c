#include "test.h"
#include "core/anim.h"
#include "core/beat.h"

/* 8.8 ticks per frame at 59.7275 fps: 48 * bpm / 60 / 59.7275 * 256. */
#define RATE_120 411
#define RATE_140 480

/* The placeholder light attack: 3 frames over an 8th note, hit on the 2nd (hit=2 -> index 1). */
static const uint16_t light_ends[] = { 8, 14, 24 };
/* The placeholder idle: 2 frames over two beats, looping. */
static const uint16_t idle_ends[] = { 48, 96 };

static uint32_t song_pos(const beat_clock_t *c)
{
    return (uint32_t)c->beat * BEAT_TICKS + c->tick;
}

/* The frame the ends table says should show `ticks` into the anim. */
static uint8_t expected_frame(const uint16_t *ends, uint8_t n, uint32_t ticks, uint8_t loop)
{
    uint8_t i;
    if (loop)
        ticks %= ends[n - 1];
    for (i = 0; i < n; i++)
        if (ticks < ends[i])
            return i;
    return n - 1;
}

void test_anim_frames_follow_ends(void)
{
    anim_t a;
    unsigned t, frames = 0, hits = 0, dones = 0;
    uint8_t ev;

    anim_play(&a, light_ends, 3, 1, 0, 0);
    ev = anim_advance(&a, 0);
    CHECK_EQ(ev, ANIM_EV_FRAME); /* the start is reported, with no hit (hit frame is 1) */
    CHECK_EQ(a.frame, 0);
    for (t = 1; t <= 30; t++) {
        ev = anim_advance(&a, 1);
        CHECK_EQ(a.frame, expected_frame(light_ends, 3, t, 0));
        if (ev & ANIM_EV_FRAME)
            frames++;
        if (ev & ANIM_EV_HIT) {
            hits++;
            CHECK_EQ(t, 8); /* the hit frame starts exactly at ends[0] */
        }
        if (ev & ANIM_EV_DONE) {
            dones++;
            CHECK_EQ(t, 24);
        }
        CHECK_EQ(anim_done(&a), t >= 24);
    }
    CHECK_EQ(frames, 2);
    CHECK_EQ(hits, 1);
    CHECK_EQ(dones, 1);
    CHECK_EQ(a.frame, 2); /* holds its last frame */

    /* A big step that jumps over the hit frame still reports the hit. */
    anim_play(&a, light_ends, 3, 1, 0, 0);
    anim_advance(&a, 0);
    ev = anim_advance(&a, 20);
    CHECK_EQ(ev, ANIM_EV_FRAME | ANIM_EV_HIT);
    CHECK_EQ(a.frame, 2);
    ev = anim_advance(&a, 200);
    CHECK_EQ(ev, ANIM_EV_DONE);

    /* Starting inside the hit frame reports the hit with the start. */
    anim_play(&a, light_ends, 3, 1, 0, 10);
    CHECK_EQ(anim_advance(&a, 0), ANIM_EV_FRAME | ANIM_EV_HIT);
    CHECK_EQ(a.frame, 1);
    anim_play(&a, light_ends, 3, 0, 0, 0);
    CHECK_EQ(anim_advance(&a, 0), ANIM_EV_FRAME | ANIM_EV_HIT);
    anim_play(&a, light_ends, 3, ANIM_NO_HIT, 0, 0);
    CHECK_EQ(anim_advance(&a, 0), ANIM_EV_FRAME);
    CHECK_EQ(anim_advance(&a, 30), ANIM_EV_FRAME | ANIM_EV_DONE);
}

void test_anim_loops(void)
{
    anim_t a;
    unsigned t, frames = 0;
    uint8_t ev;

    anim_play(&a, idle_ends, 2, ANIM_NO_HIT, ANIM_LOOP, 0);
    anim_advance(&a, 0);
    for (t = 1; t <= 400; t++) {
        ev = anim_advance(&a, 1);
        CHECK_EQ(a.frame, expected_frame(idle_ends, 2, t, 1));
        CHECK_EQ(ev & ANIM_EV_DONE, 0);
        if (ev & ANIM_EV_FRAME)
            frames++;
    }
    CHECK_EQ(frames, 8); /* changes at 48, 96, 144, ... 384 */
    CHECK_EQ(anim_done(&a), 0);

    /* A step longer than the whole loop lands in the right place. */
    anim_play(&a, idle_ends, 2, ANIM_NO_HIT, ANIM_LOOP, 0);
    anim_advance(&a, 0);
    anim_advance(&a, 250); /* 250 = 2 * 96 + 58 */
    CHECK_EQ(a.pos, 58);
    CHECK_EQ(a.frame, 1);
}

/* Drive a real beat clock through a tempo change and check, on every video frame, that the anim
 * shows exactly the frame its ends table gives for the song position. Frame boundaries are then on
 * the same musical positions at both tempos, and each one shows on the first video frame at or past
 * it. */
void test_anim_tempo_change_keeps_frames_on_the_beat(void)
{
    beat_clock_t clk;
    anim_clock_t ac;
    anim_t idle, atk;
    uint32_t idle_start, atk_start = 0, prev = 0, pos;
    unsigned f, attacks = 0, boundaries = 0;
    uint8_t ev, ticks, prev_idle_frame;

    beat_clock_start(&clk, RATE_120);
    for (f = 0; f < 37; f++) /* start somewhere mid-beat */
        beat_clock_step(&clk);
    anim_clock_sync(&ac, &clk);
    idle_start = song_pos(&clk) - anim_loop_phase(&clk, 96);
    CHECK_EQ(idle_start % 96, 0); /* phase-locked: the loop restarts every second beat */
    anim_play(&idle, idle_ends, 2, ANIM_NO_HIT, ANIM_LOOP, anim_loop_phase(&clk, 96));
    anim_advance(&idle, 0);
    prev_idle_frame = idle.frame;

    for (f = 0; f < 2000; f++) {
        if (f == 1000)
            clk.rate = RATE_140; /* the song's tempo map changes */
        prev = song_pos(&clk);
        beat_clock_step(&clk);
        pos = song_pos(&clk);

        ticks = anim_clock_ticks(&ac, &clk);
        ev = anim_advance(&idle, ticks);
        CHECK_EQ(idle.frame, expected_frame(idle_ends, 2, pos - idle_start, 1));
        if (idle.frame != prev_idle_frame) {
            /* A boundary at a multiple of 48 ticks was crossed during this video frame. */
            CHECK_EQ((pos - idle_start) % 48 < pos - prev, 1);
            CHECK_EQ(ev & ANIM_EV_FRAME, ANIM_EV_FRAME);
            boundaries++;
        }
        prev_idle_frame = idle.frame;

        /* An attack every 101 video frames, checked against the song the same way. */
        if (f % 101 == 0) {
            anim_play(&atk, light_ends, 3, 1, 0, 0);
            anim_advance(&atk, 0);
            atk_start = pos;
            attacks++;
        } else if (attacks) {
            anim_advance(&atk, ticks);
            CHECK_EQ(atk.frame, expected_frame(light_ends, 3, pos - atk_start, 0));
        }
    }
    CHECK_EQ(boundaries > 60, 1);
    CHECK_EQ(attacks, 20);
}

/* The same check for a one-shot, one video frame at a time, across the tempo change. */
void test_anim_one_shot_across_tempo_change(void)
{
    beat_clock_t clk;
    anim_clock_t ac;
    anim_t atk;
    uint32_t start;
    unsigned f, shot, hit_seen;
    uint8_t ev;

    for (shot = 0; shot < 40; shot++) {
        beat_clock_start(&clk, RATE_120);
        for (f = 0; f < 3 + shot * 7; f++)
            beat_clock_step(&clk);
        anim_clock_sync(&ac, &clk);
        start = song_pos(&clk);
        anim_play(&atk, light_ends, 3, 1, 0, 0);
        anim_advance(&atk, 0);
        hit_seen = 0;
        for (f = 0; f < 30; f++) {
            uint32_t prev = song_pos(&clk), pos;
            if (f == (shot % 12))
                clk.rate = RATE_140; /* change tempo at a different point of each attack */
            beat_clock_step(&clk);
            pos = song_pos(&clk);
            ev = anim_advance(&atk, anim_clock_ticks(&ac, &clk));
            CHECK_EQ(atk.frame, expected_frame(light_ends, 3, pos - start, 0));
            if (ev & ANIM_EV_HIT) {
                hit_seen++;
                /* reported on the video frame that crossed tick 8 of the attack */
                CHECK_EQ(prev - start < 8 && pos - start >= 8, 1);
            }
            if (ev & ANIM_EV_DONE)
                CHECK_EQ(prev - start < 24 && pos - start >= 24, 1);
        }
        CHECK_EQ(hit_seen, 1);
        CHECK_EQ(anim_done(&atk), 1);
    }
}

void test_anim_hitstop_freezes_then_catches_up(void)
{
    anim_t a;
    unsigned t;
    uint8_t ev, frames = 0;

    anim_play(&a, light_ends, 3, 1, 0, 0);
    anim_advance(&a, 0);
    for (t = 1; t <= 8; t++)
        ev = anim_advance(&a, 1);
    CHECK_EQ(ev, ANIM_EV_FRAME | ANIM_EV_HIT);
    CHECK_EQ(a.frame, 1);

    anim_hitstop(&a, 10); /* freeze the hit frame for 10 ticks: through tick 18 */
    for (t = 9; t <= 24; t++) {
        ev = anim_advance(&a, 1);
        if (t < 18) {
            CHECK_EQ(a.frame, 1);         /* frozen, though tick 14 starts frame 2 musically */
            CHECK_EQ(ev, 0);
        } else if (t == 18) {
            CHECK_EQ(a.frame, 2);         /* caught up: the frame the beat says */
            CHECK_EQ(ev, ANIM_EV_FRAME);
            frames++;
        } else if (t == 24) {
            CHECK_EQ(ev, ANIM_EV_DONE);   /* still ends on the beat */
        } else {
            CHECK_EQ(ev, 0);
        }
        CHECK_EQ(a.mframe, expected_frame(light_ends, 3, t, 0));
    }
    CHECK_EQ(frames, 1);

    /* A hitstop longer than the rest of the anim holds the hit frame, then reports DONE. */
    anim_play(&a, light_ends, 3, 1, 0, 0);
    anim_advance(&a, 0);
    anim_advance(&a, 8);
    anim_hitstop(&a, 24);
    for (t = 9; t < 32; t++) {
        CHECK_EQ(anim_advance(&a, 1), 0);
        CHECK_EQ(a.frame, 1);
        CHECK_EQ(anim_done(&a), 0);
    }
    CHECK_EQ(anim_advance(&a, 1), ANIM_EV_FRAME | ANIM_EV_DONE); /* tick 32: freeze over */
    CHECK_EQ(a.frame, 2);

    /* Overlapping hitstops keep the longer one; a big step ends a freeze in one go. */
    anim_play(&a, idle_ends, 2, ANIM_NO_HIT, ANIM_LOOP, 40);
    anim_advance(&a, 0);
    anim_hitstop(&a, 20);
    anim_hitstop(&a, 5);
    CHECK_EQ(a.freeze, 20);
    CHECK_EQ(anim_advance(&a, 19), 0);
    CHECK_EQ(a.frame, 0);
    CHECK_EQ(a.mframe, 1);
    CHECK_EQ(anim_advance(&a, 1), ANIM_EV_FRAME);
    CHECK_EQ(a.frame, 1);

    /* anim_play clears a running freeze. */
    anim_hitstop(&a, 50);
    anim_play(&a, light_ends, 3, 1, 0, 0);
    anim_advance(&a, 0);
    anim_advance(&a, 10);
    CHECK_EQ(a.frame, 1);
}

void test_anim_clock_ticks(void)
{
    beat_clock_t c;
    anim_clock_t ac;

    beat_clock_start(&c, RATE_120);
    c.beat = 7;
    c.tick = 40;
    anim_clock_sync(&ac, &c);
    CHECK_EQ(anim_clock_ticks(&ac, &c), 0);

    c.tick = 46;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 6);
    c.beat = 8; /* wrap across the beat */
    c.tick = 1;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 3);
    c.beat = 10; /* a stalled main loop: two beats and a bit */
    c.tick = 5;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 100);
    c.beat = 15; /* five more beats: 244, still fits */
    c.tick = 9;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 244);
    c.beat = 20; /* 5 beats + 31 ticks: saturates */
    c.tick = 40;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 255);
    c.beat = 40; /* too far: resync */
    CHECK_EQ(anim_clock_ticks(&ac, &c), 0);
    c.beat = 0; /* the song restarted */
    c.tick = 2;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 0);
    c.tick = 3;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 1);

    /* The beat counter wraps at 65536. */
    c.beat = 0xFFFF;
    c.tick = 47;
    anim_clock_sync(&ac, &c);
    c.beat = 0;
    c.tick = 1;
    CHECK_EQ(anim_clock_ticks(&ac, &c), 2);
}

void test_anim_loop_phase(void)
{
    beat_clock_t c;

    beat_clock_start(&c, RATE_120);
    c.beat = 3;
    c.tick = 5;
    CHECK_EQ(anim_loop_phase(&c, 96), 53);  /* beat 3 is the 2nd beat of a 2-beat loop */
    CHECK_EQ(anim_loop_phase(&c, 48), 5);
    CHECK_EQ(anim_loop_phase(&c, 24), 5);
    c.tick = 30;
    CHECK_EQ(anim_loop_phase(&c, 24), 6);
    CHECK_EQ(anim_loop_phase(&c, 16), 14);
    CHECK_EQ(anim_loop_phase(&c, 72), 0);   /* 1.5 beats: unsupported, starts at 0 */
    c.beat = 7;
    CHECK_EQ(anim_loop_phase(&c, 144), 78); /* 7 mod 3 = 1 beat in, + 30 */
    c.beat = 0xFFFF;
    c.tick = 0;
    CHECK_EQ(anim_loop_phase(&c, 144), (0xFFFF % 3) * 48);
    CHECK_EQ(anim_loop_phase(&c, 96), 48);
    CHECK_EQ(anim_loop_phase(&c, 0), 0);
}

/* Turning to another drawn facing swaps the ends table but keeps the musical position, any hitstop
 * and the done state; it redraws without re-reporting the hit. */
void test_anim_retarget_keeps_position(void)
{
    static const uint16_t other_ends[] = { 6, 12, 18, 24 }; /* same 8th note, 4 frames */
    anim_t a;
    uint8_t ev;

    anim_play(&a, light_ends, 3, 1, 0, 0);
    anim_advance(&a, 0);
    CHECK_EQ(anim_advance(&a, 9), ANIM_EV_FRAME | ANIM_EV_HIT);
    anim_retarget(&a, other_ends, 4, 1, 0);
    CHECK_EQ(a.pos, 9);
    CHECK_EQ(a.frame, 1);
    CHECK_EQ(anim_advance(&a, 0), ANIM_EV_FRAME); /* redraw, no second hit */
    CHECK_EQ(anim_advance(&a, 3), ANIM_EV_FRAME); /* tick 12: frame 2 of the new table */
    CHECK_EQ(a.frame, 2);

    /* while frozen: the visible frame stays frozen (clamped to the new table) */
    anim_hitstop(&a, 10);
    anim_retarget(&a, light_ends, 3, 1, 0);
    CHECK_EQ(a.mframe, 1);
    CHECK_EQ(a.frame, 2);
    CHECK_EQ(a.freeze, 10);
    ev = anim_advance(&a, 0);
    CHECK_EQ(ev, ANIM_EV_FRAME);
    CHECK_EQ(a.frame, 2);
    anim_advance(&a, 10); /* tick 22: freeze over, musical frame 2 */
    CHECK_EQ(a.frame, 2);
    CHECK_EQ(anim_advance(&a, 2), ANIM_EV_DONE);
    anim_retarget(&a, other_ends, 4, 1, 0);
    CHECK_EQ(anim_done(&a), 1);
    CHECK_EQ(a.frame, 3);
    CHECK_EQ(anim_advance(&a, 5), ANIM_EV_FRAME); /* no second DONE */

    /* a loop wraps the kept position into the new length */
    anim_play(&a, idle_ends, 2, ANIM_NO_HIT, ANIM_LOOP, 90);
    anim_retarget(&a, light_ends, 3, ANIM_NO_HIT, ANIM_LOOP);
    CHECK_EQ(a.pos, 90 - 3 * 24);
    CHECK_EQ(a.frame, 2);
}

/* More frames than anim_t holds: the first 15 play on time, the last one fills the rest. */
void test_anim_long_anims_clamp(void)
{
    uint16_t ends[20];
    anim_t a;
    uint8_t i;

    for (i = 0; i < 20; i++)
        ends[i] = (uint16_t)(i + 1) * 4;
    anim_play(&a, ends, 20, 17, 0, 0);
    CHECK_EQ(a.frame_count, ANIM_MAX_FRAMES);
    anim_advance(&a, 0);
    anim_advance(&a, 59);
    CHECK_EQ(a.frame, 14);
    anim_advance(&a, 1);
    CHECK_EQ(a.frame, 15);
    CHECK_EQ(anim_advance(&a, 19), 0);
    CHECK_EQ(anim_advance(&a, 1), ANIM_EV_DONE); /* still ends at 80 ticks */
}

/* ANIM_ADVANCE_QUIET is the caller-side fast path: when it takes a step, anim_advance would have
 * reported nothing. Two anims fed the same ticks, one through the fast path, never differ. */
void test_anim_quiet_fast_path_matches(void)
{
    anim_t a, b;
    unsigned f, fast = 0;
    uint8_t t, ea, eb;

    anim_play(&a, light_ends, 3, 1, 0, 0);
    anim_play(&b, light_ends, 3, 1, 0, 0);
    for (f = 0; f < 400; f++) {
        t = (uint8_t)(f % 3); /* 0, 1, 2 ticks per frame */
        if (f % 37 == 0) {
            anim_play(&a, f % 74 ? light_ends : idle_ends, f % 74 ? 3 : 2, f % 74 ? 1 : ANIM_NO_HIT,
                      f % 74 ? 0 : ANIM_LOOP, 0);
            anim_play(&b, f % 74 ? light_ends : idle_ends, f % 74 ? 3 : 2, f % 74 ? 1 : ANIM_NO_HIT,
                      f % 74 ? 0 : ANIM_LOOP, 0);
        }
        if (f % 53 == 10) {
            anim_hitstop(&a, 6);
            anim_hitstop(&b, 6);
        }
        ea = anim_advance(&a, t);
        if (ANIM_ADVANCE_QUIET(&b, t)) {
            eb = 0;
            fast++;
        } else {
            eb = anim_advance(&b, t);
        }
        CHECK_EQ(eb, ea);
        CHECK_EQ(b.frame, a.frame);
        CHECK_EQ(b.pos, a.pos);
    }
    CHECK_EQ(fast > 200, 1);
}
