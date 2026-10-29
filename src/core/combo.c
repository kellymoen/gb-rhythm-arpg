#ifdef __SDCC
#pragma bank 255
#endif

#include <stddef.h>

#include "core/combo.h"
#include "tuning.h"

/* Combo string matcher; rules in combo.h. Called from the main loop on every press and frame, so it
 * stays in 8/16-bit adds and compares: strings are walked by pointer (no index * sizeof multiply)
 * and step slots are compared by subtraction, so they may wrap. */

#define BUTTONS (COMBO_A | COMBO_B)
#define NO_FIT 0xFF

enum { HELD_NONE, HELD, HELD_LANDED }; /* combo_t.pending */
#define ATTACKS offsetof(combo_string_t, attacks) /* attacks[k] is steps[k] + ATTACKS */

static void emit(combo_event_t *e, uint8_t type, uint8_t string, uint8_t step, uint8_t attack, grade_t grade)
{
    e->type = type;
    e->string = string;
    e->step = step;
    e->attack = attack;
    e->grade = grade;
}

static void go_idle(combo_t *c)
{
    c->run.string = COMBO_IDLE;
    c->run.cands = c->all;
    c->run.pos = 0xFF; /* the next step is step 0 */
    c->run.step = 0;
}

void combo_reset_with(combo_t *c, const combo_string_t *strings, uint8_t count) CORE_BANKED
{
    c->strings = strings;
    c->count = count;
    c->all = count ? (uint8_t)(0xFF >> (8 - count)) : 0;
    c->pending = HELD_NONE;
    c->held_n = 0;
    c->hit.ev.type = COMBO_EV_NONE;
    go_idle(c);
}

void combo_reset(combo_t *c) CORE_BANKED
{
    combo_reset_with(c, combos.strings, COMBO_STRING_COUNT);
}

/* Ends the current string, if any, with a BREAK. Returns the number of events written (0 or 1). */
static uint8_t end_string(combo_t *c, combo_event_t *out)
{
    if (c->run.string == COMBO_IDLE)
        return 0;
    emit(out, COMBO_EV_BREAK, c->run.string, c->run.step, COMBO_NO_ATTACK, GRADE_OFFBEAT);
    go_idle(c);
    return 1;
}

/* Inputs and outputs of probe(), and advance()'s running result. Statics, because SDCC addresses
 * them directly while stack locals cost an `ldhl sp` per access; the matcher runs in the main loop
 * only, so it need not be reentrant. */
static uint8_t p_gap, p_grace, p_button, p_dir, p_room; /* the press, and steps left after c->run.pos */
static uint8_t p_k, p_attack, p_after;                  /* where it landed, its attack, rests after */
static uint8_t best_rank, best_mask, best_k, best_string, best_attack;
static uint8_t done_string, done_attack, max_rests;

#define COMPLETES 0xFF /* p_after: no step follows, the press completes the string */

/* Does the press fit the string whose next step is at p? Returns its rank (lower is better: fewest
 * grace slots, then the held-direction variant over a plain step) or NO_FIT. Small on purpose, so
 * SDCC keeps the walking pointer in registers. */
static uint8_t probe(const uint8_t *p)
{
    uint8_t n = p_room, r = 0, t, rank;

    /* Skip the written rests before the next step: the gap must cover them. */
    for (;;) {
        if (!n)
            return NO_FIT; /* string over */
        t = *p;
        if (t != COMBO_STEP_REST)
            break;
        p++;
        n--;
        r++;
    }
    if (p_gap < r) /* the press fell on a written rest */
        return NO_FIT;
    r = p_gap - r; /* unwritten empty slots */
    if (r > p_grace)
        return NO_FIT;
    if ((t & COMBO_STEP_BUTTONS) != p_button) /* also rejects END */
        return NO_FIT;
    rank = (uint8_t)(r << 1) | 1;
    t >>= COMBO_STEP_DIR_SHIFT;
    if (t) {
        if (t != p_dir)
            return NO_FIT;
        rank--;
    }
    p_k = (uint8_t)(COMBO_MAX_STEPS - n);
    p_attack = p[ATTACKS];

    /* What follows: rests and then the end (the press completes the string), or the next step. */
    for (r = 0;; r++) {
        p++;
        if (!--n || *p == COMBO_STEP_END) {
            r = COMPLETES;
            break;
        }
        if (*p != COMBO_STEP_REST)
            break;
    }
    p_after = r;
    return rank;
}

/* Try to land a single-button press on the candidates. On a fit, updates the string and writes a
 * STEP or FINISH; returns 0 when no candidate fits (the state is then unchanged). */
static uint8_t advance(combo_t *c, const combo_input_t *in, uint8_t gap, combo_event_t *out)
{
    const uint8_t *steps;
    uint8_t cands = c->run.cands, left = c->count, i, bit, rank, first = (uint8_t)(c->run.pos + 1);

    p_gap = gap;
    p_grace = (uint8_t)tuning.combat_string_grace;
    p_button = in->buttons;
    p_dir = in->dir;
    p_room = (uint8_t)(COMBO_MAX_STEPS - first);
    steps = c->strings->steps + first;
    best_rank = NO_FIT;
    best_mask = 0;
    for (i = 0, bit = 1; left; i++, left--, bit <<= 1, cands >>= 1, steps += sizeof(combo_string_t)) {
        if (!(cands & 1))
            continue;
        rank = probe(steps);
        if (rank == NO_FIT || rank > best_rank)
            continue;
        /* Ties stay candidates together. Survivors share one fit, so they landed on one step index. */
        if (rank < best_rank) {
            best_rank = rank;
            best_mask = 0;
            best_k = p_k;
            best_string = i;
            best_attack = p_attack;
            done_string = COMBO_IDLE;
            max_rests = 0;
        }
        best_mask |= bit;
        if (p_after == COMPLETES) {
            if (done_string == COMBO_IDLE) {
                done_string = i;
                done_attack = p_attack;
            }
        } else if (p_after > max_rests) {
            max_rests = p_after;
        }
    }
    if (!best_mask)
        return 0;

    if (done_string != COMBO_IDLE) {
        emit(out, COMBO_EV_FINISH, done_string, c->run.step, done_attack, in->judgement.grade);
        go_idle(c);
        return 1;
    }
    /* Report the lowest survivor; the deadline is the latest slot any survivor could take its next
     * step on. */
    emit(out, COMBO_EV_STEP, best_string, c->run.step, best_attack, in->judgement.grade);
    c->run.string = best_string;
    c->run.cands = best_mask;
    c->run.pos = best_k;
    c->run.step++;
    c->run.last_slot = in->judgement.slot;
    c->run.deadline = in->judgement.slot + 1 + max_rests + p_grace;
    return 1;
}

/* Land one A or B press. Returns the number of events written (0..2) and sets c->hit to the step
 * it became, if any. */
static uint8_t land(combo_t *c, const combo_input_t *in, combo_event_t *out)
{
    uint8_t n = 0, gap = 0;

    if (c->run.string != COMBO_IDLE) {
        uint16_t d = in->judgement.slot - c->run.last_slot;
        if ((int16_t)d <= 0) /* that slot is taken already */
            return 0;
        d--;
        gap = d > 0xFE ? 0xFE : (uint8_t)d;
        if (advance(c, in, gap, out)) {
            n = 1;
            goto landed;
        }
        n = end_string(c, out);
        gap = 0;
    }
    n += advance(c, in, gap, out + n);
landed:
    if (n && out[n - 1].type != COMBO_EV_BREAK) {
        c->hit.ev = out[n - 1];
        c->hit.slot = in->judgement.slot;
        c->hit.frame = in->frame;
        c->hit.buttons = in->buttons;
    }
    return n;
}

/* Land the held press provisionally: its events wait in held_ev until it commits. */
static void land_held(combo_t *c)
{
    c->undo = c->run;
    c->held_n = land(c, &c->held, c->held_ev);
    c->pending = HELD_LANDED;
}

static uint8_t dodge(combo_t *c, grade_t grade, combo_event_t *out)
{
    uint8_t n = end_string(c, out);

    emit(out + n, COMBO_EV_DODGE, COMBO_IDLE, 0, COMBO_NO_ATTACK, grade);
    return n + 1;
}

/* A dodge undoes the press held back for it: if it landed, the run goes back to before it, and if
 * it had become a step, `hit` says to cancel that step's musical hit. */
static uint8_t undo_and_dodge(combo_t *c, grade_t grade, combo_event_t *out)
{
    if (c->pending == HELD_LANDED) {
        c->run = c->undo;
        if (c->held_n && c->held_ev[c->held_n - 1].type != COMBO_EV_BREAK)
            c->hit.ev.type = COMBO_EV_DODGE;
    }
    c->pending = HELD_NONE;
    return dodge(c, grade, out);
}

/* Report the held press's events (it can no longer become part of a dodge). */
static uint8_t commit(combo_t *c, combo_event_t *out)
{
    uint8_t i;

    if (c->pending == HELD)
        land_held(c);
    c->pending = HELD_NONE;
    for (i = 0; i < c->held_n; i++)
        out[i] = c->held_ev[i];
    return c->held_n;
}

uint8_t combo_press(combo_t *c, const combo_input_t *in, combo_event_t out[COMBO_MAX_EVENTS]) CORE_BANKED
{
    uint8_t grace = (uint8_t)tuning.input_dodge_grace;
    uint8_t buttons = in->buttons & BUTTONS, n = 0;

    c->hit.ev.type = COMBO_EV_NONE;
    if (!buttons)
        return 0;
    if (c->pending) {
        /* The other button within dodge_grace: a dodge, graded like the earlier press. */
        if ((buttons & ~c->held.buttons) && (uint8_t)(in->frame - c->held.frame) <= grace)
            return undo_and_dodge(c, c->held.judgement.grade, out);
        /* A+B together supersedes a press still held back (it would only just have started). */
        if (buttons == BUTTONS)
            return undo_and_dodge(c, in->judgement.grade, out);
        n = commit(c, out);
    }
    if (buttons == BUTTONS) /* (nothing was held back, so out is empty) */
        return dodge(c, in->judgement.grade, out);
    if (!grace && !n)
        return land(c, in, out);
    /* Hold it back until combo_land or the combo_tick that commits it lands it (also when
     * dodge_grace just changed to 0 under a held press: out may be full, so the next combo_tick
     * reports it). */
    c->held = *in;
    c->held.buttons = buttons;
    c->pending = HELD;
    return n;
}

void combo_land(combo_t *c) CORE_BANKED
{
    c->hit.ev.type = COMBO_EV_NONE;
    if (c->pending == HELD)
        land_held(c);
}

uint8_t combo_tick(combo_t *c, const beat_clock_t *now, uint8_t frame, combo_event_t out[COMBO_MAX_EVENTS]) CORE_BANKED
{
    c->hit.ev.type = COMBO_EV_NONE;
    if (c->pending) {
        /* Signed: a press newer than `frame` (queued while the scene drained) is not due yet. */
        if ((int8_t)(frame - c->held.frame) < (int8_t)tuning.input_dodge_grace)
            return 0; /* it may still continue the string, so don't break it under it */
        return commit(c, out);
    }
    /* Only a running string needs the slot, so idle frames skip beat_slot_now. */
    if (c->run.string != COMBO_IDLE && (int16_t)(beat_slot_now(now) - c->run.deadline) > 0)
        return end_string(c, out);
    return 0;
}
