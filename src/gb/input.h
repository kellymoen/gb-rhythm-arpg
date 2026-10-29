#ifndef GB_INPUT_H
#define GB_INPUT_H

#include <stdint.h>

#include "core/beat.h"

/* Joypad sampling happens in the VBlank ISR so A/B presses are judged against the beat clock on the
 * exact frame they happen, even if the main loop is running slow (ADR 0004). */

typedef struct {
    uint8_t buttons; /* J_A and/or J_B newly pressed this frame */
    uint8_t held;    /* every button held at the press, incl. the D-pad (direction variants) */
    uint8_t frame;   /* input_frame at the press */
    judgement_t judgement;
} press_t;

extern volatile uint8_t input_held;

/* VBlank count, wrapping. Measures short gaps between presses (e.g. dodge_grace). */
extern volatile uint8_t input_frame;

#ifdef DEBUG
/* Every judged press, for the feel lab and timing overlay: a ring the ISR writes at
 * press_log[press_log_head & (PRESS_LOG_SIZE - 1)], then increments press_log_head. */
#define PRESS_LOG_SIZE 16 /* power of two */
typedef struct {
    uint8_t frame;
    uint8_t buttons;
    uint8_t grade;   /* grade_t */
    int8_t frames;   /* judgement.frames: < 0 early, > 0 late */
} press_log_t;
extern press_log_t press_log[PRESS_LOG_SIZE];
extern volatile uint8_t press_log_head;
#endif

/* VBlank ISR: sample the joypad. Returns the press it queued this frame, if any. */
const press_t *input_poll(void);

/* Main loop: drop every queued press (scene changes). */
void input_flush(void);

/* Main loop: take the oldest queued press. Returns 0 when the queue is empty. */
uint8_t input_pop(press_t *out);

/* Main loop: buttons that went down since the previous call (for menus, not for combat). */
uint8_t input_edges(void);

#endif
