#pragma bank 255

#include <gb/gb.h>

#include "audio/music.h"
#include "core/anim.h"
#include "core/budgets.h"
#include "core/iso.h"
#include "gb/fx.h"
#include "gb/hud.h"
#include "gb/input.h"
#include "gb/oam.h"
#include "gb/spriteanim.h"
#include "gb/text.h"
#include "gb/video.h"
#include "gb/vram_stream.h"
#include "music.h"
#include "scenes/scene.h"
#include "sprite_dummy.h"
#include "sprite_player.h"
#include "tuning.h"

/* Combat scene, M2 wave 1b: a sprite viewer on a flat floor. The player plays anims to the rhythm-
 * test song; the D-pad turns them (8 facings), A/B step through the actions (one-shots return to
 * idle). The training dummy idles beside them and flinches when an attack's hit frame lands, with
 * hitstop on both. Integration builds combat on top of this. */

#define ORIGIN_X 80 /* screen px of world (0, 0) */
#define ORIGIN_Y 92
#define PX(p) ((int16_t)(p) << ISO_SUBPX_SHIFT)
/* PROVISIONAL viewer layout: the dummy stands to the right of the player, slightly behind. */
#define DUMMY_WX PX(18)
#define DUMMY_WY PX(-22)
#define ENEMY_SLOT_TILES (BUDGET_ENEMY_W / 8 * (BUDGET_ENEMY_H / 8))

/* PROVISIONAL: the stream copies until LY 124, leaving time to rewrite the OAM if a frame finished
 * (only when LY < 132 by then) before the VBlank OAM DMA at 144. */
#define STREAM_DEADLINE_LY 124
#define REDRAW_LIMIT_LY 132

#define ROW_ACTION 1
#define ROW_FACING 2
#define ROW_HELP 15

static const char *const action_names[] = {
    "IDLE    ", "WALK    ", "DODGE   ", "HURT    ", "LIGHT1  ", "LIGHT2  ",
    "LIGHT3  ", "LIGHT4  ", "FINISHER", "HEAVY1  ", "HEAVY2  ", "LUNGE   ",
};
#define NAMED_ACTIONS (sizeof action_names / sizeof action_names[0])
static const char *const facing_names[FACING_COUNT] = { "S ", "SE", "E ", "NE", "N ", "NW", "W ", "SW" };

/* Global so the ROM tests can inspect them. */
spriteanim_t combat_player, combat_dummy;
static anim_clock_t clock;
static beat_clock_t now;
static uint8_t hitstop_ticks;

/* The viewer's per-frame work budget: starting an anim, turning, or showing a new frame each cost
 * ~15-25 scanlines with SDCC, so it does one per frame and queues the rest (PROVISIONAL). */
static uint8_t work, want;
#define WANT_IDLE 0x01       /* the player's one-shot ended */
#define WANT_DUMMY_IDLE 0x02
#define WANT_HURT 0x04       /* the player's hit frame landed */

static uint8_t take_work(void)
{
    if (work)
        return 0;
    work = 1;
    return 1;
}

/* Held D-pad -> facing (screen-aligned, ADR 0003); FACING_COUNT when no direction is held. */
static uint8_t held_facing(uint8_t held)
{
    if (held & J_UP)
        return held & J_RIGHT ? FACING_NE : held & J_LEFT ? FACING_NW : FACING_N;
    if (held & J_DOWN)
        return held & J_RIGHT ? FACING_SE : held & J_LEFT ? FACING_SW : FACING_S;
    if (held & J_RIGHT)
        return FACING_E;
    if (held & J_LEFT)
        return FACING_W;
    return FACING_COUNT;
}

/* Play the next (step 1) or previous (step -1) action the player has art for. */
static void step_action(int8_t step)
{
    uint8_t a = combat_player.action, tries;

    for (tries = 0; tries < SPRITE_PLAYER_ACTION_COUNT; tries++) {
        if (step > 0)
            a = a + 1 < SPRITE_PLAYER_ACTION_COUNT ? a + 1 : 0;
        else
            a = a ? a - 1 : SPRITE_PLAYER_ACTION_COUNT - 1;
        if (spriteanim_play(&combat_player, a, combat_player.facing, &now))
            return;
    }
}

static void print_action(uint8_t a)
{
    if (a < NAMED_ACTIONS)
        text_print(1, ROW_ACTION, action_names[a]);
    else
        text_print_int(1, ROW_ACTION, a, 8, 0);
}

static int16_t player_x, player_y, player_depth, dummy_x, dummy_y, dummy_depth;

static void place(void)
{
    iso_screen_t p;

    iso_project(0, 0, &p);
    player_x = ORIGIN_X + p.x;
    player_y = ORIGIN_Y + p.y;
    player_depth = iso_depth(0, 0);
    iso_project(DUMMY_WX, DUMMY_WY, &p);
    dummy_x = ORIGIN_X + p.x;
    dummy_y = ORIGIN_Y + p.y;
    dummy_depth = iso_depth(DUMMY_WX, DUMMY_WY);
}

static void draw_world(void)
{
    oam_begin();
    spriteanim_draw(&combat_player, player_x, player_y, player_depth);
    spriteanim_draw(&combat_dummy, dummy_x, dummy_y, dummy_depth);
    oam_end();
}

scene_t combat_viewer(void) BANKED;
scene_t combat_viewer(void) BANKED
{
    press_t press;
    uint8_t ev, f, ticks, have_press = 0, shown_action = 0xFF, shown_facing = 0xFF;

    scene_begin();
    hud_init();
    vram_stream_reset();
    SPRITEANIM_INIT(&combat_player, player, TILE_PLAYER_SPR, BUDGET_FRAME_TILES);
    SPRITEANIM_INIT(&combat_dummy, dummy, TILE_WORLD_SPR, ENEMY_SLOT_TILES);
    music_play(BANK(song_rhythmtest), &song_rhythmtest); /* the clock waits for VBlank, i.e. scene_show */
    music_now(&now);
    anim_clock_sync(&clock, &now);
    spriteanim_play(&combat_player, SPRITE_PLAYER_IDLE, FACING_S, &now);
    spriteanim_play(&combat_dummy, SPRITE_DUMMY_IDLE, FACING_S, &now);
    spriteanim_update(&combat_player, 0);
    spriteanim_update(&combat_dummy, 0);
    vram_stream_update(0xFF); /* LCD off: both first frames now */
    place();
    draw_world();
    text_print(1, ROW_HELP, "DPAD:FACE  A/B:ACT");
    text_print(1, ROW_HELP + 1, "START: BACK");
    hitstop_ticks = (uint8_t)tuning.hitstop_good_ticks;
    want = 0;
    scene_show();

    while (1) {
        vsync();
        music_now(&now);
        ticks = anim_clock_ticks(&clock, &now);

        /* Anims first; at most one new frame is shown per video frame. */
        spriteanim_presents = 1;
        ev = spriteanim_update(&combat_player, ticks);
        if (spriteanim_update(&combat_dummy, ticks) & ANIM_EV_DONE)
            want |= WANT_DUMMY_IDLE;
        work = !spriteanim_presents;
        if (ev & ANIM_EV_DONE)
            want |= WANT_IDLE;
        if (ev & ANIM_EV_HIT) { /* the player freezes now; the dummy flinches and freezes */
            spriteanim_hitstop(&combat_player, hitstop_ticks);
            want |= WANT_HURT;
        }

        /* Then at most one costly start or turn per frame (SDCC makes each ~20 scanlines). A press
         * waits for the frame after it: that frame's VBlank ISR already paid for grading it. */
        if (!have_press && input_pop(&press))
            have_press = 1;
        if (have_press && press.frame != input_frame && take_work()) {
            /* PROVISIONAL: the viewer's hitstop follows the grade of the press that started it */
            hitstop_ticks = (uint8_t)(press.judgement.grade == GRADE_PERFECT ? tuning.hitstop_perfect_ticks
                                      : press.judgement.grade == GRADE_GOOD ? tuning.hitstop_good_ticks
                                                                            : tuning.hitstop_offbeat_ticks);
            step_action(press.buttons & J_A ? 1 : -1);
            have_press = 0;
            want &= (uint8_t)~WANT_IDLE;
        }
        if ((want & WANT_HURT) && take_work()) {
            spriteanim_play(&combat_dummy, SPRITE_DUMMY_HURT, FACING_S, &now);
            spriteanim_hitstop(&combat_dummy, hitstop_ticks);
            want &= (uint8_t)~(WANT_HURT | WANT_DUMMY_IDLE);
        }
        if ((want & WANT_IDLE) && take_work()) {
            spriteanim_play(&combat_player, SPRITE_PLAYER_IDLE, combat_player.facing, &now);
            want &= (uint8_t)~WANT_IDLE;
        }
        if ((want & WANT_DUMMY_IDLE) && take_work()) {
            spriteanim_play(&combat_dummy, SPRITE_DUMMY_IDLE, FACING_S, &now);
            want &= (uint8_t)~WANT_DUMMY_IDLE;
        }
        f = held_facing(input_held);
        if (f != FACING_COUNT && f != combat_player.facing && take_work())
            spriteanim_face(&combat_player, f);

        draw_world();
        hud_update();
        fx_update();

        /* at most one text job, and only on a frame with nothing else heavy (slow with the LCD on) */
        if (!work) {
            if (combat_player.action != shown_action) {
                shown_action = combat_player.action;
                print_action(shown_action);
            } else if (combat_player.facing != shown_facing) {
                shown_facing = combat_player.facing;
                text_print(1, ROW_FACING, facing_names[shown_facing]);
            }
        }

        if (input_edges() & J_START)
            return SCENE_MENU;

        /* last: stream tiles in the time left, and show frames that finished in time */
        if (vram_stream_update(STREAM_DEADLINE_LY) && LY_REG < REDRAW_LIMIT_LY) {
            spriteanim_show_ready(&combat_player);
            spriteanim_show_ready(&combat_dummy);
            oam_end();
        }
    }
}

/* main() calls scenes through plain pointers, so the entry point stays in bank 0. */
scene_t combat_run(void) NONBANKED
{
    return combat_viewer();
}
