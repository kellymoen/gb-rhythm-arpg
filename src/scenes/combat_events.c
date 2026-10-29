#pragma bank 255

#include <gb/gb.h>

#include "audio/sfx.h"
#include "core/combo.h"
#include "gb/fx.h"
#include "gb/spriteanim.h"
#include "scenes/combat.h"
#include "sfx.h"
#include "sprite_player.h"
#include "tuning.h"

/* What the combat scene does about combo events, hit frames and beats (combat.h). Each runs a few
 * times per second at most, so these are plain banked calls. Every rule here is PROVISIONAL. */

/* combos.toml sfx names -> sound effect ids (generated X-macro list). */
#define SFX_ID(n) SFX_##n,
static const uint8_t combo_sfx[COMBO_SFX_COUNT] = { COMBO_SFX_LIST(SFX_ID) };
#undef SFX_ID

/* The training dummy's strike cycle (PROVISIONAL, M2 only: real telegraphs and attack tokens are M3). */
enum { DUMMY_IDLE, DUMMY_TELEGRAPH };
static uint8_t dummy_state, dummy_count, dummy_telegraph_left;

void combat_events_init(void) BANKED
{
    combat_stats.damage = combat_stats.dummy_hits = 0;
    combat_stats.hits = combat_stats.last_damage = 0;
    combat_stats.finished = COMBO_IDLE;
    combat_stats.finishes = combat_stats.breaks = combat_stats.steps = combat_stats.dodges = 0;
    combat_stats.slowmos = combat_stats.strikes = combat_stats.player_hurts = combat_stats.strikes_dodged = 0;
    combat_stats.last_grade = GRADE_OFFBEAT;
    combat_stats.last_attack = COMBO_NO_ATTACK;
    combat_stats.attacks_started = 0;
    dummy_state = DUMMY_IDLE;
    dummy_count = 0;
}

static uint8_t hitstop_for(uint8_t grade)
{
    return (uint8_t)(grade == GRADE_PERFECT ? tuning.hitstop_perfect_ticks
                     : grade == GRADE_GOOD  ? tuning.hitstop_good_ticks
                                            : tuning.hitstop_offbeat_ticks);
}

uint8_t combat_dodging(void) BANKED
{
    return combat_pending == PENDING_DODGE || (combat_busy && combat_player.action == SPRITE_PLAYER_DODGE);
}

/* A dodge read after the strike's beat still beats it if its press was judged at most good_window
 * frames from the beat (by the press's own frame, so a slow main loop changes nothing). */
static uint8_t late_dodge_in_time(void)
{
    int8_t d = (int8_t)(combat_press_frame - combat_strike_frame), w = (int8_t)tuning.timing_good_window;

    return d >= -w && d <= w;
}

void combat_on_event(const combo_event_t *e) BANKED
{
    const combo_attack_t *a;
    uint8_t beats;

    switch (e->type) {
    case COMBO_EV_STEP:
    case COMBO_EV_FINISH:
        a = &combos.attacks[e->attack];
        combat_pending = PENDING_ATTACK;
        combat_pending_attack = e->attack;
        combat_pending_grade = e->grade;
        if (e->type == COMBO_EV_FINISH)
            combat_pending_heavy = 1;
        /* the swing sounds at once; the hit sound waits for the hit frame */
        sfx_play(a->sfx != COMBO_NO_SFX ? combo_sfx[a->sfx]
                 : combat_pending_heavy ? SFX_SWING_HEAVY : SFX_SWING_LIGHT);
        if (e->step == 0) {
            combat_stats.hits = 0;
            combat_ui_counters();
            combat_ui_name(NAME_BLANK);
        }
        combat_stats.steps++;
        combat_stats.last_grade = e->grade;
        combat_stats.last_attack = e->attack;
        if (e->type == COMBO_EV_FINISH) {
            combat_stats.finished = e->string;
            combat_stats.finishes++;
            combat_ui_name(e->string);
        }
        break;
    case COMBO_EV_BREAK:
        if (e->step) {
            combat_stats.breaks++;
            combat_ui_name(NAME_BREAK);
            if (e->step >= 2) /* PROVISIONAL: a lone stray hit breaking makes no sound */
                sfx_play(SFX_STRING_BREAK);
        }
        break;
    case COMBO_EV_DODGE:
        combat_pending = PENDING_DODGE;
        combat_stats.dodges++;
        if (combat_strike_waits && late_dodge_in_time()) { /* inside the GOOD window */
            combat_strike_waits = 0;
            combat_stats.strikes_dodged++;
        }
        if (e->grade == GRADE_PERFECT && tuning.slowmo_beats > 0) {
            beats = (uint8_t)tuning.slowmo_beats;
            combat_slowmo = ((uint16_t)beats << 5) + ((uint16_t)beats << 4); /* x BEAT_TICKS (48) */
            fx_set_dim(1);
            combat_stats.slowmos++;
            sfx_play(SFX_PERFECT);
            combat_ui_name(NAME_PERFECT_DODGE);
        } else {
            sfx_play(SFX_DODGE);
            combat_ui_name(NAME_DODGE);
        }
        break;
    }
}

void combat_on_hit_frame(void) BANKED
{
    box_t hb, hu;
    int16_t px = combat_px >> 4, py = combat_py >> 4, ax, ay, bx, by, d;
    uint8_t atk = combat_attack, dmg, shift, hs;

    if (atk == COMBO_NO_ATTACK)
        return;
    if (!spriteanim_hitbox(&combat_player, &hb))
        return;
    spriteanim_hurtbox(&combat_dummy, &hu);
    combat_attack = COMBO_NO_ATTACK; /* one hit per attack */
    if (!hu.w || !hb.w)
        return;
    d = py - DUMMY_Y;
    if (d < 0)
        d = -d;
    if (d > tuning.combat_hit_depth_px)
        return;
    ax = px + hb.x;
    ay = py + hb.y;
    bx = DUMMY_X + hu.x;
    by = DUMMY_Y + hu.y;
    if (ax >= bx + hu.w || bx >= ax + hb.w || ay >= by + hu.h || by >= ay + hb.h)
        return;

    dmg = combos.attacks[atk].damage;
    if (combat_attack_grade == GRADE_OFFBEAT) {
        shift = (uint8_t)tuning.combat_offbeat_damage_shift;
        for (; shift && dmg; shift--)
            dmg >>= 1;
    }
    if (combat_stats.damage <= 0xFFFF - dmg)
        combat_stats.damage += dmg;
    combat_stats.dummy_hits++;
    if (combat_stats.hits < 99)
        combat_stats.hits++;
    combat_stats.last_damage = dmg;
    combat_ui_counters();

    /* hitstop on both characters; the dummy's flinch starts when the frame budget allows and
     * carries the freeze with it */
    hs = hitstop_for(combat_attack_grade);
    spriteanim_hitstop(&combat_player, hs);
    spriteanim_hitstop(&combat_dummy, hs);
    combat_dummy_hitstop = hs;
    combat_want = (combat_want & (uint8_t)~WANT_DUMMY_IDLE) | WANT_DUMMY_HURT;
    sfx_play(combat_attack_heavy ? SFX_HIT_HEAVY : SFX_HIT);
    combat_flash();
}

/* The dummy's strike lands on this beat (PROVISIONAL). */
static void strike(void)
{
    int16_t dx = (combat_px >> 4) - DUMMY_X, dy = (combat_py >> 4) - DUMMY_Y, range = tuning.dummy_range_px;
    uint16_t pos;

    combat_stats.strikes++;
    if (dx < 0)
        dx = -dx;
    if (dy < 0)
        dy = -dy;
    sfx_play(SFX_SWING_HEAVY);
    if (dx > range || (dy << 1) > range) { /* a whiff: the mark shows in front of the dummy */
        combat_strike_mark(DUMMY_X + ((combat_px >> 4) < DUMMY_X ? -12 : 12), DUMMY_Y - 14);
        return;
    }
    combat_strike_mark(combat_px >> 4, (combat_py >> 4) - 14);
    if (combat_dodging()) {
        combat_stats.strikes_dodged++;
        combat_ui_name(NAME_DODGED);
        return;
    }
    /* a dodge pressed up to good_window frames late still counts (the press is graded against
     * this beat, so it can be a perfect dodge). Counted in VBlanks (input_frame) from the one a
     * press judged exactly on the beat is read on, as beat_judge counts: the loop may see the beat
     * late, so step back the frames since the beat, rounded, by subtraction; then the latency
     * offset. */
    combat_strike_waits = 1;
    combat_strike_frame = combat_frame + (int8_t)tuning.timing_latency_offset;
    pos = (((uint16_t)combat_now.tick << 8) | combat_now.frac) + (combat_now.rate >> 1);
    if (combat_now.rate)
        for (; pos >= combat_now.rate; pos -= combat_now.rate)
            combat_strike_frame--;
}

void combat_strike_lands(void) BANKED
{
    combat_stats.player_hurts++;
    combat_want |= WANT_PLAYER_HURT;
    sfx_play(SFX_HIT_HEAVY);
    combat_ui_name(NAME_OUCH);
}

void combat_on_beat(void) BANKED
{
    uint8_t every = (uint8_t)tuning.dummy_attack_every_beats;

    if (!every) {
        if (dummy_state != DUMMY_IDLE)
            combat_telegraph(0);
        dummy_state = DUMMY_IDLE;
        dummy_count = 0;
        return;
    }
    if (dummy_state == DUMMY_TELEGRAPH && --dummy_telegraph_left == 0) {
        dummy_state = DUMMY_IDLE;
        combat_telegraph(0);
        strike(); /* a telegraphed strike lands on its beat, slow-mo or not */
    }
    if (combat_slowmo) /* no new telegraph during slow-mo: the player's window to punish */
        return;
    if (++dummy_count >= every) {
        dummy_count = 0;
        if (dummy_state == DUMMY_IDLE) {
            dummy_state = DUMMY_TELEGRAPH;
            dummy_telegraph_left = tuning.dummy_telegraph_beats > 0 ? (uint8_t)tuning.dummy_telegraph_beats : 1;
            combat_telegraph(1);
        }
    }
}
