#ifndef CORE_COMBO_H
#define CORE_COMBO_H

#include <stdint.h>

#include "core/beat.h"

/* Combo string matcher (ADR 0004). Portable: the scene feeds it judged presses and step-slot
 * changes, and it reports what the player did. Strings, steps and attacks come from
 * data/combos.toml via tools/gbtools/combos.py (in DEBUG builds the table lives in RAM so the
 * feel lab can edit it live).
 *
 * Rules (PROVISIONAL defaults, see docs/decisions-pending.md):
 * - A step lands on the step slot its press is graded against. OFFBEAT steps still advance the
 *   string, flagged so the scene can weaken them.
 * - A written rest ('.') is a step slot that must stay empty.
 * - An unwritten empty step slot ends the string after `combat.string_grace` slots.
 * - A and B within `input.dodge_grace` frames is a dodge, not two attacks. */

#define COMBO_A 0x01
#define COMBO_B 0x02

/* Held direction at the time of the press, relative to the player's facing. */
enum { COMBO_DIR_NONE, COMBO_DIR_FWD, COMBO_DIR_BACK, COMBO_DIR_SIDE };

typedef struct {
    uint8_t buttons;       /* COMBO_A and/or COMBO_B newly pressed */
    uint8_t dir;           /* COMBO_DIR_* */
    uint8_t frame;         /* ISR frame counter at the press (wraps), for dodge_grace */
    judgement_t judgement;
} combo_input_t;

enum {
    COMBO_EV_NONE,
    COMBO_EV_STEP,         /* an attack step landed: play attack `attack` */
    COMBO_EV_FINISH,       /* the step that completed string `string` (also carries its attack) */
    COMBO_EV_BREAK,        /* the current string ended without finishing */
    COMBO_EV_DODGE         /* A+B: `grade` PERFECT means a perfect dodge (slow-mo) */
};

typedef struct {
    uint8_t type;          /* COMBO_EV_* */
    uint8_t string;        /* index into the generated string table */
    uint8_t step;          /* 0-based step within the string: also the musical-hit pitch index */
    uint8_t attack;        /* index into the generated attack table (anim, damage, lunge...) */
    grade_t grade;
} combo_event_t;

typedef struct {
    uint8_t string;        /* candidate string, or 0xFF when idle */
    uint8_t step;
    uint16_t last_slot;
    uint8_t empty_slots;
    uint8_t pending;       /* a lone A/B held back for dodge_grace frames */
    combo_input_t held;
} combo_t;

void combo_reset(combo_t *c);

/* Feed one press. Returns the number of events written to `out` (0..2: a held-back press can
 * resolve as a step and the new press start another). */
uint8_t combo_press(combo_t *c, const combo_input_t *in, combo_event_t out[2]);

/* Call once per main-loop frame with the current step slot and frame counter: resolves held-back
 * presses after dodge_grace and breaks strings after string_grace empty slots. Returns the number
 * of events written (0..2). */
uint8_t combo_tick(combo_t *c, uint16_t slot, uint8_t frame, combo_event_t out[2]);

#endif
