#ifndef CORE_COMBO_H
#define CORE_COMBO_H

#include <stdint.h>

#include "combos.h"
#include "core/banked.h"
#include "core/beat.h"

/* Combo string matcher (ADR 0004). Portable: the scene feeds it judged presses and the beat clock,
 * and it reports what the player did. Strings, steps and attacks come from data/combos.toml via
 * tools/gbtools/combos.py (generated combos.h: in DEBUG builds the table lives in RAM so the feel lab
 * can edit it live; the matcher rereads it on every press).
 *
 * Rules (PROVISIONAL defaults, see docs/decisions-pending.md):
 * - A step lands on the step slot its press is graded against. OFFBEAT steps still advance the
 *   string, flagged (event grade) so the scene can weaken them.
 * - A written rest ('.') is a step slot that must stay empty: a press there breaks the string.
 * - An unwritten empty step slot is slack: the string survives `combat.string_grace` of them in a
 *   row, and breaks on the next.
 * - A and B within `input.dodge_grace` frames is a dodge, not two attacks. Its grade is the earlier
 *   press's; a PERFECT dodge is a perfect dodge (slow-mo). A dodge ends the current string.
 * - A second press judged against the slot the string's last step already took is ignored.
 * - Strings that start with the same steps stay candidates together until they diverge. When a press
 *   fits several, the one that needs the fewest grace slots wins (so the rest in `A A . A` beats
 *   the slack `A A _ A` of `A A A A`), then the one whose step names the held direction (fB beats B).
 *
 * - A held-back press can land provisionally before it commits (combo_land): its events are kept
 *   and reported when it commits (after dodge_grace, as before), but combo_hit() names the step it
 *   became straight away, so the scene can schedule its musical hit without waiting. A dodge undoes
 *   the landing.
 *
 * Driving it from the main loop, every frame:
 *     frame = input_frame;                   read BEFORE draining the queue (dodge_grace timing)
 *     while (input_pop(&p)) combo_press(...)  one combo_input_t per press
 *     music_now(&now);
 *     combo_tick(&c, &now, frame, ev)
 * and act on the events each call returns. Main loop only: the matcher is not reentrant. */

#define COMBO_A 0x01 /* same bits as a step byte's button (generated combos.h) */
#define COMBO_B 0x02

/* Held direction at the time of the press, relative to the player's facing (a step byte's bits 2-3). */
enum { COMBO_DIR_NONE, COMBO_DIR_FWD, COMBO_DIR_BACK, COMBO_DIR_SIDE };

#define COMBO_IDLE 0xFF   /* combo_t.string / combo_event_t.string when no string is involved */
#define COMBO_MAX_EVENTS 2

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
    uint8_t string;        /* COMBO_STRING_*: STEP/BREAK name the lowest-numbered string still
                            * possible, FINISH the one completed. COMBO_IDLE for DODGE */
    uint8_t step;          /* STEP/FINISH: 0-based hit within the string (rests don't count), also
                            * the musical-hit pitch index. BREAK: hits landed before it broke */
    uint8_t attack;        /* COMBO_ATTACK_* (index into combos.attacks), or COMBO_NO_ATTACK */
    grade_t grade;         /* the press's grade (DODGE: the earlier press's); OFFBEAT for BREAK */
} combo_event_t;

/* Where the matcher is in a string. */
typedef struct {
    uint8_t string;        /* lowest candidate string, or COMBO_IDLE */
    uint8_t cands;         /* bitmask of strings the steps so far still fit */
    uint8_t pos;           /* step index (rests included) of the last landed step */
    uint8_t step;          /* hits landed so far */
    uint16_t last_slot;    /* step slot of the last landed step */
    uint16_t deadline;     /* last slot a press can still continue some candidate */
} combo_run_t;

/* What a press means for musical hits (combo_hit()). */
typedef struct {
    combo_event_t ev;      /* type, step (the HITS pitch) and grade, see combo_hit() */
    uint16_t slot;         /* the press's step slot, frame and buttons */
    uint8_t frame;
    uint8_t buttons;
} combo_hit_t;

/* Private: read only through events and combo_hit(). */
typedef struct {
    const combo_string_t *strings;
    uint8_t count;
    uint8_t all;           /* bitmask of every string */
    combo_run_t run;
    uint8_t pending;       /* a lone A/B held back for dodge_grace frames (and landed provisionally) */
    combo_input_t held;
    combo_run_t undo;      /* the run before the held press landed (a dodge restores it) */
    uint8_t held_n;        /* its events, reported when it commits */
    combo_event_t held_ev[COMBO_MAX_EVENTS];
    combo_hit_t hit;
} combo_t;

/* What the last combo_press, combo_land or combo_tick decided for musical hits, at once (a press
 * held back for dodge_grace is decided when it lands; its events still come when it commits):
 *   ev.type COMBO_EV_STEP / _FINISH  a press became that step: ev.step is its HITS pitch, ev.grade
 *                                    its grade; schedule its hit (slot, frame, buttons: the press).
 *   ev.type COMBO_EV_DODGE           a dodge undid a held-back press that had become a step: cancel
 *                                    that step's hit if it has not played.
 *   ev.type COMBO_EV_NONE            nothing for musical hits. */
#define combo_hit(c) ((const combo_hit_t *)&(c)->hit)


/* Start idle, matching against the generated table (combos.strings). */
void combo_reset(combo_t *c) CORE_BANKED;

/* Start idle, matching against `count` (<= 8) strings at `strings`, which must be in bank 0 or RAM. */
void combo_reset_with(combo_t *c, const combo_string_t *strings, uint8_t count) CORE_BANKED;

/* Feed one press. Returns the number of events written to `out` (0..2: a held-back press can
 * resolve as BREAK + STEP, a dodge can end a string: BREAK + DODGE). */
uint8_t combo_press(combo_t *c, const combo_input_t *in, combo_event_t out[COMBO_MAX_EVENTS]) CORE_BANKED;

/* Land a press held back for dodge_grace now, provisionally, if it has not landed yet: combo_hit()
 * then names the step it became. Costs what a landing costs (combo_tick pays it when it commits
 * otherwise), so the scene calls it when the frame has room, as early as it can. */
void combo_land(combo_t *c) CORE_BANKED;

/* Call once per main-loop frame after the presses, with the beat clock (music_now) and the frame
 * counter read before draining the press queue: resolves held-back presses after dodge_grace and
 * breaks strings after string_grace empty slots. While a string runs it computes beat_slot_now(now),
 * the slot a press made now would be judged against; idle frames skip that. Returns the number of
 * events written (0..2). */
uint8_t combo_tick(combo_t *c, const beat_clock_t *now, uint8_t frame, combo_event_t out[COMBO_MAX_EVENTS]) CORE_BANKED;

#endif
