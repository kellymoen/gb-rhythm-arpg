#ifndef GB_INPUT_H
#define GB_INPUT_H

#include <stdint.h>

#include "core/beat.h"

/* Joypad sampling happens in the VBlank ISR so A/B presses are judged against the beat clock on the
 * exact frame they happen, even if the main loop is running slow (ADR 0004). */

typedef struct {
    uint8_t buttons; /* J_A and/or J_B newly pressed this frame */
    judgement_t judgement;
} press_t;

extern volatile uint8_t input_held;

/* VBlank ISR: sample the joypad. Returns the press it queued this frame, if any. */
const press_t *input_poll(void);

/* Main loop: take the oldest queued press. Returns 0 when the queue is empty. */
uint8_t input_pop(press_t *out);

/* Main loop: buttons that went down since the previous call (for menus, not for combat). */
uint8_t input_edges(void);

#endif
