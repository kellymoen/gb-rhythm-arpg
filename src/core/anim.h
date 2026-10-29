#ifndef CORE_ANIM_H
#define CORE_ANIM_H

#include <stdint.h>

#include "core/banked.h"
#include "core/beat.h"

/* Beat-relative animation playback (ADR 0004). Portable: the ROM and the host tests share it.
 *
 * An anim's position is counted in song ticks, fed from successive beat clock readings, so its frames
 * land on the same musical positions at any tempo. Frame i shows while the position is below ends[i]
 * (cumulative ticks, the layout of sprite_anim_t.ends in gb/spritedata.h).
 *
 * Two frame indices are kept apart. The musical frame is where the song says the anim is; the visible
 * frame follows it, except during hitstop, when it freezes. When the freeze ends the visible frame
 * jumps straight to the musical one (catch-up), so the anim stays locked to the beat.
 *
 * Hitstop only shows on the attacker when the freeze outlasts the rest of the hit frame: catch-up
 * then shortens or skips the frames after it.
 *
 * anim_play() and anim_retarget() copy `ends`. On the Game Boy it must be in RAM (this code runs from
 * its own ROM bank): copy the ROM table into anim_t.ends and pass that. Per-frame code: 8- and 16-bit
 * adds and compares only; ANIM_ADVANCE_QUIET lets callers skip the call on frames with no event. */

/* This code reads no ROM data, so it lives in a switchable bank (core/banked.h). ANIM_FN is the old name
 * of CORE_BANKED, kept until anim.c's definitions switch over. */
#define ANIM_FN CORE_BANKED

/* Same values as gb/spritedata.h, which this portable header cannot include (it needs GBDK). */
#ifndef ANIM_LOOP
#define ANIM_LOOP 0x01   /* restart after the last frame */
#endif
#ifndef ANIM_NO_HIT
#define ANIM_NO_HIT 0xFF /* hit_frame of an anim with no hit frame */
#endif

/* anim_advance() events */
#define ANIM_EV_FRAME 0x01 /* the visible frame changed (or the anim just started): show it */
#define ANIM_EV_HIT 0x02   /* the musical position entered the hit frame: its hitbox is live */
#define ANIM_EV_DONE 0x04  /* a one-shot reached its end and no hitstop holds it; it now holds its
                            * last frame. Reported once. */

#define ANIM_MAX_FRAMES 16 /* longer anims show their first 15 frames, then the last one */

typedef struct {
    uint16_t ends[ANIM_MAX_FRAMES]; /* a RAM copy, so playback never needs the data's ROM bank */
    uint16_t pos;     /* song ticks since the start (loops wrap, one-shots stop at the end) */
    uint8_t frame_count;
    uint8_t hit_frame;
    uint8_t flags;    /* ANIM_LOOP */
    uint8_t mframe;   /* musical frame */
    uint8_t frame;    /* visible frame */
    uint8_t freeze;   /* hitstop ticks left */
    uint8_t state;    /* internal */
    uint8_t quiet;    /* ticks that may pass with nothing but pos changing (0: call anim_advance) */
} anim_t;

/* Start an anim `start` ticks in (0 = from its first frame; anim_loop_phase() for loops). The next
 * anim_advance() reports ANIM_EV_FRAME, plus ANIM_EV_HIT when it starts inside its hit frame.
 * Clears any hitstop. */
void anim_play(anim_t *a, const uint16_t *ends, uint8_t frame_count, uint8_t hit_frame,
               uint8_t flags, uint16_t start) CORE_BANKED;

/* Swap in another ends table of the same action (the character turned to another drawn facing),
 * keeping the musical position, any hitstop and the done state. The next anim_advance() reports
 * ANIM_EV_FRAME, never a second ANIM_EV_HIT. */
void anim_retarget(anim_t *a, const uint16_t *ends, uint8_t frame_count, uint8_t hit_frame,
                   uint8_t flags) CORE_BANKED;

/* Advance by `ticks` song ticks (see anim_clock_ticks). Returns ANIM_EV_* bits. */
uint8_t anim_advance(anim_t *a, uint8_t ticks) CORE_BANKED;

/* Caller-side fast path, for 8-bit targets where a call costs more than the work: if `t` ticks
 * cannot cause any event, move the position and yield 1; else yield 0 and call anim_advance(). */
#define ANIM_ADVANCE_QUIET(a, t) ((t) < (a)->quiet && ((a)->quiet -= (t), (a)->pos += (t), 1))

/* Hitstop: freeze the visible frame for `ticks` song ticks from now (the longer of this and any
 * freeze already running). The musical position keeps moving underneath. */
void anim_hitstop(anim_t *a, uint8_t ticks) CORE_BANKED;

/* 1 once a one-shot is over (as reported by ANIM_EV_DONE). Loops never finish. */
uint8_t anim_done(const anim_t *a) CORE_BANKED;

/* Start position that lines a looping anim up with the song, so a loop of k beats restarts on beats
 * that are multiples of k and a loop of a beat fraction restarts on that subdivision. Supports
 * lengths that divide BEAT_TICKS or are whole beats (k <= 255); any other length returns 0. Call
 * when an anim starts, not every frame (it has a short divide loop). */
uint16_t anim_loop_phase(const beat_clock_t *now, uint16_t len) CORE_BANKED;

/* Song ticks elapsed between successive beat clock readings (music_now() on the Game Boy). */
typedef struct {
    uint16_t beat;
    uint8_t tick;
} anim_clock_t;

/* Remember `now` as the last reading. Call when a scene (or song) starts. */
void anim_clock_sync(anim_clock_t *c, const beat_clock_t *now) CORE_BANKED;

/* Ticks since the last reading, then remember `now`. Saturates at 255. A clock that went backwards
 * (the song restarted) or jumped more than ANIM_CLOCK_MAX_BEATS returns 0 and resyncs. */
#define ANIM_CLOCK_MAX_BEATS 5
uint8_t anim_clock_ticks(anim_clock_t *c, const beat_clock_t *now) CORE_BANKED;

#endif
