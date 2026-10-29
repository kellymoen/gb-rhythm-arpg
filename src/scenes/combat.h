#ifndef SCENES_COMBAT_H
#define SCENES_COMBAT_H

#include <gb/gb.h>
#include <stdint.h>

#include "core/beat.h"
#include "core/combo.h"
#include "gb/spriteanim.h"
#include "gb/video.h"

/* The M2 combat scene (src/scenes/combatflat.c + combat_*.c): the player, the training dummy, combo
 * strings, hits, dodges and slow-mo on the combat song. Everything here is PROVISIONAL until the
 * author has played it (docs/decisions-pending.md).
 *
 * Files: combatflat.c runs the frame (anims, input, movement, drawing, frame budget); combat_events.c
 * reacts to combo events, hit frames and beats (rare, so banked calls are fine); combat_ui.c owns the
 * grade popups, the dummy's telegraph and strike mark, the hit flash and the text counters.
 *
 * VRAM and OAM beyond video.h's owners: */
#define TILE_POPUP_SPR TILE_UI_SPR   /* 0x84-0x87: the grade popup on screen (one 16x16 cell, streamed) */
#define TILE_FX_SPR 0xB8             /* 0xB8-0xBB: "!" telegraph, strike mark (the dummy's slots end at 0xB7) */
#define TILE_FLOOR (TILE_UI + 8)     /* 0x48-0x4F: the floor diamond (hud.c uses 0x40-0x41) */
#define OAM_POPUP OAM_UI             /* 8, 9: the grade popup's two 8x16 halves */
#define OAM_TELEGRAPH (OAM_UI + 2)   /* 10 */
#define OAM_STRIKE (OAM_UI + 3)      /* 11 */

/* Screen layout (px). The dummy stands right of centre; the player starts to its left. */
#define DUMMY_X 104
#define DUMMY_Y 88
#define PLAYER_START_X 56
#define PLAYER_START_Y 96
#define PLAYER_MIN_X 12              /* the player's feet stay inside the floor */
#define PLAYER_MAX_X 148
#define PLAYER_MIN_Y 48
#define PLAYER_MAX_Y 132

/* What the scene has done, for the counters on screen and for the ROM tests (tests/rom/test_combat.py
 * reads this struct by offset through the symbol _combat_stats; keep the order). */
typedef struct {
    uint16_t damage;        /* 0: total damage dealt to the dummy */
    uint16_t dummy_hits;    /* 2: attacks whose hitbox met the dummy */
    uint8_t hits;           /* 4: hits that connected in the current (or last) string */
    uint8_t last_damage;    /* 5 */
    uint8_t finished;       /* 6: COMBO_STRING_* of the last finished string, COMBO_IDLE before any */
    uint8_t finishes;       /* 7 */
    uint8_t breaks;         /* 8: strings that broke after at least one hit */
    uint8_t steps;          /* 9: STEP + FINISH events */
    uint8_t dodges;         /* 10 */
    uint8_t slowmos;        /* 11: perfect dodges (slow-mo starts) */
    uint8_t strikes;        /* 12: dummy strikes */
    uint8_t player_hurts;   /* 13: strikes that hurt the player */
    uint8_t strikes_dodged; /* 14 */
    uint8_t last_grade;     /* 15: grade of the last attack step */
    uint8_t last_attack;    /* 16: COMBO_ATTACK_* of the last attack step */
    uint8_t attacks_started;/* 17: attack anims started */
} combat_stats_t;
extern combat_stats_t combat_stats;

/* Costly work (an anim start or turn, ~20-25 scanlines each with SDCC) the frame scheduler runs at
 * most one of per frame, in this priority order. Attacks and dodges are served first, by
 * combat_pending. */
#define WANT_PLAYER_HURT 0x01
#define WANT_DUMMY_HURT 0x02
#define WANT_DUMMY_IDLE 0x04
extern uint8_t combat_want;

/* The next player action the scheduler starts (an attack step or a dodge). */
#define PENDING_NONE 0
#define PENDING_ATTACK 1
#define PENDING_DODGE 2
extern uint8_t combat_pending;
extern uint8_t combat_pending_attack;  /* COMBO_ATTACK_* */
extern uint8_t combat_pending_grade;   /* grade_t of its press */
extern uint8_t combat_pending_heavy;   /* B step or a finisher: heavy hit sound */
extern uint8_t combat_pending_held;    /* D-pad held at the press, for the soft lock and the dodge dash */

/* The attack the player's current anim is playing (its hit frame deals it), or COMBO_NO_ATTACK. */
extern uint8_t combat_attack, combat_attack_grade, combat_attack_heavy;

extern spriteanim_t combat_player, combat_dummy;
extern beat_clock_t combat_now;
extern int16_t combat_px, combat_py;   /* player feet, 1/16 screen px */
extern uint8_t combat_busy;            /* the player is in an attack, dodge or hurt anim */
extern uint16_t combat_slowmo;         /* song ticks of slow-mo left */
extern uint8_t combat_frame;           /* input_frame when the loop read combat_now */
extern uint8_t combat_press_frame;     /* input_frame of the press the matcher is reading */
extern uint8_t combat_strike_waits;    /* a strike in range waits for a dodge pressed up to... */
extern uint8_t combat_strike_frame;    /* ...good_window VBlanks after this one, its beat's */
extern uint8_t combat_dummy_hitstop;   /* hitstop for the dummy's hurt anim when it starts */

/* combat_events.c */
void combat_events_init(void) BANKED;
void combat_on_event(const combo_event_t *e) BANKED;  /* one matcher event */
void combat_on_hit_frame(void) BANKED;               /* the player's anim entered its hit frame */
void combat_on_beat(void) BANKED;                    /* the beat clock reached a new beat */
void combat_strike_lands(void) BANKED;               /* a strike's dodge grace ran out */
uint8_t combat_dodging(void) BANKED;

/* combat_ui.c */
void combat_ui_init(void) BANKED;     /* LCD off: tiles, palettes, labels; registers the popup stream job */
void combat_popup(uint8_t grade) BANKED;
void combat_telegraph(uint8_t on) BANKED;
void combat_strike_mark(int16_t x, int16_t y) BANKED;
void combat_flash(void) BANKED;       /* start the dummy's hit flash */
void combat_ui_update(uint8_t ticks) BANKED;  /* every frame, before the world is drawn */
uint8_t combat_ui_text(void) BANKED;  /* one pending text job; returns 0 when there was none */

/* Text the name row shows (combat_ui_name). Strings use their COMBO_STRING_* index. */
enum { NAME_BREAK = 0x80, NAME_DODGE, NAME_PERFECT_DODGE, NAME_OUCH, NAME_DODGED, NAME_BLANK };
void combat_ui_name(uint8_t name) BANKED;
void combat_ui_counters(void) BANKED; /* damage and hit counters changed */

#endif
