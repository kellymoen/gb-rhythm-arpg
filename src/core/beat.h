#ifndef CORE_BEAT_H
#define CORE_BEAT_H

#include <stdint.h>

/* Musical time (ADR 0004). The sound driver advances one beat clock per VBlank; gameplay reads it.
 * Song ticks: BEAT_TICKS per beat, so 8ths = 24, 16ths = 12, triplet 8ths = 16. */
#define BEAT_TICKS 48

typedef struct {
    uint16_t beat; /* whole beats since song start */
    uint8_t tick;  /* 0..BEAT_TICKS-1 within the beat */
    uint8_t frac;  /* 1/256 tick */
    uint16_t rate; /* ticks per frame, 8.8 fixed point (set by the song's tempo map) */
} beat_clock_t;

void beat_clock_start(beat_clock_t *c, uint16_t rate);

/* Advance one frame. Returns the number of whole ticks that elapsed. */
uint8_t beat_clock_step(beat_clock_t *c);

typedef enum {
    GRADE_OFFBEAT,
    GRADE_GOOD,
    GRADE_PERFECT
} grade_t;

typedef struct {
    grade_t grade;
    int8_t frames; /* distance to the nearest step slot: < 0 early, > 0 late */
    uint16_t slot; /* index of that step slot since song start */
} judgement_t;

/* Grade an input made at the clock's current position against the nearest step slot, using the
 * timing tuning params (steps_per_beat must divide BEAT_TICKS). */
void beat_judge(const beat_clock_t *c, judgement_t *j);

/* Whole ticks from the clock's position until step slot `slot` (0 if it is now or past). */
uint16_t beat_ticks_until_slot(const beat_clock_t *c, uint16_t slot);

#endif
