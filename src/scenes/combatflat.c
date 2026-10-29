#pragma bank 255

#include <gb/gb.h>

#include "audio/music.h"
#include "audio/sfx.h"
#include "core/anim.h"
#include "core/budgets.h"
#include "core/combo.h"
#include "gb/fx.h"
#include "gb/hud.h"
#include "gb/input.h"
#include "gb/isr.h"
#include "gb/oam.h"
#include "gb/overlay.h"
#include "gb/spriteanim.h"
#include "gb/video.h"
#include "gb/vram_stream.h"
#include "music.h"
#include "scenes/combat.h"
#include "scenes/scene.h"
#include "sprite_dummy.h"
#include "sprite_player.h"
#include "tuning.h"

/* Combat scene, M2: the player against the training dummy on a flat floor, to the combat song.
 * This file runs the frame; combat_events.c and combat_ui.c hold the rarer work (see combat.h).
 *
 * Frame order and budget (docs/perf.md, "M2 combat scene"):
 *   1. palette (fx), beat clock
 *   2. presses -> combo matcher (which schedules each step's musical hit at once), matcher tick ->
 *      events. Grading already happened in the VBlank ISR, on the press's own frame.
 *   3. the player's next attack or dodge starts (what matters most for feel goes first)
 *   4. anims advance (at most one new frame shown per video frame), hit frames are judged
 *   5. beat work (dummy telegraph and strike), slow-mo countdown
 *   6. at most one other costly job: hurt / flinch / walk / idle / turn anims
 *   7. movement, popups and flash, OAM, HUD, timing overlay, one text job if nothing costly ran
 *   8. tile streaming in the time left, then a late OAM rewrite if a frame finished in time.
 * Each costly step only starts before its LY limit below, so stacked work slips a frame instead of
 * overrunning one. A loop that starts late (the VBlank ISR ran long: many song events, a graded
 * press) leaves presses queued and does no costly work; a very late one only draws, and both
 * characters' song ticks carry over to the next frame so their anims stay on the beat. */

#define ENEMY_SLOT_TILES (BUDGET_ENEMY_W / 8 * (BUDGET_ENEMY_H / 8))

/* PROVISIONAL frame budget (docs/perf.md). */
#define STREAM_DEADLINE_LY 120 /* tile streaming stops here (a copy may run ~4 lines past)... */
#define REDRAW_LIMIT_LY 126    /* ...and a late OAM rewrite (up to ~12 lines) starts before this */
#define LATE_START_LY 36       /* a loop starting at or after this line leaves presses queued and
                                * does no costly work */
#define VERY_LATE_LY 64        /* ...and at or after this one only draws (anims and movement wait) */
#define POP_LIMIT_LY 64        /* another press is fed to the matcher only before this line */
#define TICK_LIMIT_LY 80       /* the matcher's tick only runs before this line */
#define LAND_LIMIT_LY 44       /* a held-back press lands early (its musical hit) before this line */
#define START_LIMIT_LY 68      /* the player's attack or dodge only starts before this line */
#define PRESENT_LIMIT_LY 60    /* a new anim frame is only shown before this line */
#define COSTLY_LIMIT_LY 64     /* step 6 only starts before this line */
#define TEXT_LIMIT_LY 100      /* a text job only starts before this line */
#define OVERLAY_LIMIT_LY 112   /* DEBUG timing overlay update (it catches up on the next frame) */
#define CARRY_MAX 24           /* an anim is never more than this many song ticks behind */

#define OVERLAY_X 128          /* DEBUG timing overlay: top right, clear of the counters */
#define OVERLAY_Y 0

/* Shared with combat_events.c and combat_ui.c (combat.h); globals so the ROM tests can read them. */
combat_stats_t combat_stats;
uint8_t combat_want, combat_pending, combat_pending_attack, combat_pending_grade, combat_pending_heavy;
uint8_t combat_pending_held;
uint8_t combat_attack, combat_attack_grade, combat_attack_heavy;
spriteanim_t combat_player, combat_dummy;
beat_clock_t combat_now;
int16_t combat_px, combat_py;
uint8_t combat_busy;
uint16_t combat_slowmo;
uint8_t combat_strike_grace, combat_dummy_hitstop;

static anim_clock_t clock;
static combo_t combo;
static combo_event_t evs[COMBO_MAX_EVENTS];
static uint16_t last_beat;
static uint8_t divider, carry_p, carry_d;
static int16_t px, py; /* the player's feet this frame, whole px */

/* Slide: a lunge toward the dummy (per axis, stopping at contact) or a dodge dash (fixed direction).
 * It eases out, moving half the distance left each frame. */
static uint8_t slide_left, slide_lunge;
static int8_t slide_sx, slide_sy;

/* combos.toml anim names -> player actions (generated X-macro lists). */
#define ACTION(n) SPRITE_PLAYER_##n,
static const uint8_t attack_action[COMBO_ANIM_COUNT] = { COMBO_ANIM_LIST(ACTION) };
#undef ACTION

static const int8_t facing_dx[FACING_COUNT] = { 0, 1, 1, 1, 0, -1, -1, -1 };
static const int8_t facing_dy[FACING_COUNT] = { 1, 1, 0, -1, -1, -1, 0, 1 };

/* Held D-pad -> facing (screen-aligned); FACING_COUNT when no direction is held. */
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

/* The held direction relative to the player's facing (PROVISIONAL: within 45 degrees counts as
 * forward or back, square to it as side). */
static uint8_t combo_dir(uint8_t held)
{
    uint8_t h = held_facing(held), d;

    if (h == FACING_COUNT)
        return COMBO_DIR_NONE;
    d = (uint8_t)(h - combat_player.facing) & 7;
    if (d <= 1 || d == 7)
        return COMBO_DIR_FWD;
    if (d >= 3 && d <= 5)
        return COMBO_DIR_BACK;
    return COMBO_DIR_SIDE;
}

static int16_t iabs(int16_t v)
{
    return v < 0 ? -v : v;
}

/* 8-way direction of a screen vector (2:1 sectors, no division). */
static uint8_t dir8(int16_t dx, int16_t dy)
{
    int16_t ax = iabs(dx), ay = iabs(dy);

    if (ax > (ay << 1))
        return dx > 0 ? FACING_E : FACING_W;
    if (ay > (ax << 1))
        return dy > 0 ? FACING_S : FACING_N;
    if (dx > 0)
        return dy > 0 ? FACING_SE : FACING_NE;
    return dy > 0 ? FACING_SW : FACING_NW;
}

/* Soft lock (PROVISIONAL): the dummy's direction if it is within lock range and within 45 degrees
 * of `ref` (the held direction, else the facing); FACING_COUNT otherwise. */
static uint8_t lock_toward(uint8_t ref)
{
    int16_t dx = DUMMY_X - px, dy = DUMMY_Y - py, range = tuning.combat_lock_range_px;
    uint8_t f, d;

    if (iabs(dx) > range || iabs(dy) > range)
        return FACING_COUNT;
    f = dir8(dx, dy);
    d = (uint8_t)(f - ref) & 7;
    return d <= 1 || d == 7 ? f : FACING_COUNT;
}

/* Would the player's feet at (x, y) (1/16 px) stand inside the dummy's footprint? Compared in 1/16 px
 * against bounds set once per frame (solid_bounds), so no shifts or calls. */
static int16_t solid_x0, solid_x1, solid_y0, solid_y1;

static void solid_bounds(void)
{
    solid_x0 = (DUMMY_X - tuning.dummy_solid_w) << 4;
    solid_x1 = ((DUMMY_X + tuning.dummy_solid_w) << 4) + 15;
    solid_y0 = (DUMMY_Y - tuning.dummy_solid_h) << 4;
    solid_y1 = ((DUMMY_Y + tuning.dummy_solid_h) << 4) + 15;
}

static uint8_t blocked(int16_t x, int16_t y)
{
    return x >= solid_x0 && x <= solid_x1 && y >= solid_y0 && y <= solid_y1;
}

/* Move by (mx, my) in 1/16 px, one axis at a time so the player slides along the dummy, inside the
 * floor. A move that would enter the footprint is refused (one that leaves it is fine). */
static void move_by(int16_t mx, int16_t my)
{
    int16_t v;
    uint8_t inside = blocked(combat_px, combat_py);

    if (mx) {
        v = combat_px + mx;
        if (v < (PLAYER_MIN_X << 4))
            v = PLAYER_MIN_X << 4;
        else if (v > (PLAYER_MAX_X << 4))
            v = PLAYER_MAX_X << 4;
        if (inside || !blocked(v, combat_py))
            combat_px = v;
    }
    if (my) {
        v = combat_py + my;
        if (v < (PLAYER_MIN_Y << 4))
            v = PLAYER_MIN_Y << 4;
        else if (v > (PLAYER_MAX_Y << 4))
            v = PLAYER_MAX_Y << 4;
        if (inside || !blocked(combat_px, v))
            combat_py = v;
    }
}

/* Toward `to` from `from` along one axis by up to `step` px, stopping `stop` px short. In 1/16 px. */
static int16_t approach(int16_t from, int16_t to, uint8_t step, int16_t stop)
{
    int16_t d = to - from;

    if (d > stop) {
        d -= stop;
        return (int16_t)(d < step ? d : step) << 4;
    }
    if (d < -stop) {
        d = -d - stop;
        return -((int16_t)(d < step ? d : step) << 4);
    }
    return 0;
}

static void slide_step(void)
{
    uint8_t step = (uint8_t)((slide_left + 1) >> 1);
    int16_t s;

    slide_left -= step;
    if (slide_lunge) {
        /* contact: one px outside the footprint on whichever axes are still apart */
        move_by(approach(combat_px >> 4, DUMMY_X, step, tuning.dummy_solid_w + 1),
                approach(combat_py >> 4, DUMMY_Y, step, tuning.dummy_solid_h + 1));
        return;
    }
    s = (int16_t)step << 4;
    if (slide_sx && slide_sy)
        s -= s >> 2;
    move_by(slide_sx > 0 ? s : slide_sx < 0 ? -s : 0, slide_sy > 0 ? s : slide_sy < 0 ? -s : 0);
}

/* Hit frames judge where the attack ends up: finish the lunge at once. */
static void slide_finish(void)
{
    solid_bounds();
    while (slide_left)
        slide_step();
}

/* Start the queued attack or dodge (one costly anim start). */
static void start_pending(void)
{
    uint8_t f = combat_player.facing, held = held_facing(combat_pending_held), lock, lunge;
    const combo_attack_t *a;

    if (combat_pending == PENDING_DODGE) {
        spriteanim_play(&combat_player, SPRITE_PLAYER_DODGE, f, &combat_now);
        combat_attack = COMBO_NO_ATTACK;
        lock = held != FACING_COUNT ? held : (uint8_t)(f + 4) & 7; /* dash direction */
        slide_sx = facing_dx[lock];
        slide_sy = facing_dy[lock];
        slide_left = (uint8_t)tuning.player_dodge_px;
        slide_lunge = 0;
    } else {
        a = &combos.attacks[combat_pending_attack];
        slide_left = 0;
        lock = lock_toward(held != FACING_COUNT ? held : f);
        if (lock != FACING_COUNT) {
            f = lock;
            lunge = a->lunge;
            if (lunge > (uint8_t)tuning.combat_lunge_px)
                lunge = (uint8_t)tuning.combat_lunge_px;
            slide_left = lunge;
            slide_lunge = 1;
        } else if (held != FACING_COUNT) {
            f = held; /* no target: the attack goes where the D-pad points */
        }
        if (!spriteanim_play(&combat_player, attack_action[a->anim], f, &combat_now))
            spriteanim_play(&combat_player, SPRITE_PLAYER_LIGHT1, f, &combat_now); /* missing art */
        combat_attack = combat_pending_attack;
        combat_attack_grade = combat_pending_grade;
        combat_attack_heavy = combat_pending_heavy;
        combat_stats.attacks_started++;
    }
    combat_busy = 1;
    combat_pending = PENDING_NONE;
}

/* At most one of these per frame, in priority order. Returns 1 if it did one. */
static uint8_t costly(void)
{
    uint8_t f;

    if (combat_want & WANT_PLAYER_HURT) {
        combat_want &= (uint8_t)~WANT_PLAYER_HURT;
        spriteanim_play(&combat_player, SPRITE_PLAYER_HURT, combat_player.facing, &combat_now);
        combat_busy = 1;
        combat_attack = COMBO_NO_ATTACK;
        slide_left = 0;
        return 1;
    }
    if (combat_want & WANT_DUMMY_HURT) {
        combat_want &= (uint8_t)~(WANT_DUMMY_HURT | WANT_DUMMY_IDLE);
        spriteanim_play(&combat_dummy, SPRITE_DUMMY_HURT, FACING_S, &combat_now);
        spriteanim_hitstop(&combat_dummy, combat_dummy_hitstop);
        carry_d = 0;
        return 1;
    }
    if (!combat_busy) {
        f = held_facing(input_held);
        if (f != FACING_COUNT) {
            if (combat_player.action != SPRITE_PLAYER_WALK) {
                spriteanim_play(&combat_player, SPRITE_PLAYER_WALK, f, &combat_now);
                return 1;
            }
            if (f != combat_player.facing) {
                spriteanim_face(&combat_player, f);
                return 1;
            }
        } else if (combat_player.action != SPRITE_PLAYER_IDLE) {
            spriteanim_play(&combat_player, SPRITE_PLAYER_IDLE, combat_player.facing, &combat_now);
            return 1;
        }
    }
    if (combat_want & WANT_DUMMY_IDLE) {
        combat_want &= (uint8_t)~WANT_DUMMY_IDLE;
        spriteanim_play(&combat_dummy, SPRITE_DUMMY_IDLE, FACING_S, &combat_now);
        carry_d = 0;
        return 1;
    }
    return 0;
}

static void walk(void)
{
    uint8_t held = input_held;
    int16_t s = tuning.player_walk_speed, mx = 0, my = 0;

    if ((held & (J_LEFT | J_RIGHT)) && (held & (J_UP | J_DOWN)))
        s -= s >> 2;
    if (held & J_RIGHT)
        mx = s;
    else if (held & J_LEFT)
        mx = -s;
    if (held & J_DOWN)
        my = s;
    else if (held & J_UP)
        my = -s;
    if (mx || my)
        move_by(mx, my);
}

static void draw_world(void)
{
    oam_begin();
    spriteanim_draw(&combat_player, px, py, py);
    spriteanim_draw(&combat_dummy, DUMMY_X, DUMMY_Y, DUMMY_Y);
    oam_end();
}

/* Musical hits (gb/isr.h): the step a press became plays its HITS pitch. The matcher decides it
 * as soon as the press lands (provisionally, in the tick on the press's own frame, while it still
 * holds the press back for dodge_grace); a dodge that undoes it cancels the hit. OFFBEAT steps play
 * none. Call after every combo_press and combo_tick. */
static void schedule_hit(void)
{
    const combo_hit_t *h = combo_hit(&combo);

    if (h->ev.type == COMBO_EV_DODGE)
        isr_hit_cancel();
    else if (h->ev.type != COMBO_EV_NONE && h->ev.grade != GRADE_OFFBEAT)
        isr_hit_schedule(h->ev.step, h->slot, h->frame, h->buttons);
}

/* Will `t` more ticks take the player's attack into its hit frame (and the frame do the hit's work)? */
static uint8_t hit_frame_due(uint8_t t)
{
    const anim_t *a = &combat_player.anim;
    uint8_t k = a->hit_frame;

    if (combat_attack == COMBO_NO_ATTACK || k == ANIM_NO_HIT || !k || a->mframe >= k)
        return 0;
    return a->pos + t >= a->ends[k - 1];
}

static void handle(uint8_t n)
{
    uint8_t i;

    for (i = 0; i < n; i++)
        combat_on_event(&evs[i]);
}

scene_t combat_scene(void) BANKED;
scene_t combat_scene(void) BANKED
{
    press_t p;
    combo_input_t in;
    uint8_t ticks, pticks, dticks, work, late, drained, started, pev, dev, frame, edges, ly, n;

    scene_begin();
    hud_init();
    vram_stream_reset();
    /* stream priority: the player's frames, then the grade popup, then the dummy */
    SPRITEANIM_INIT(&combat_player, player, TILE_PLAYER_SPR, BUDGET_FRAME_TILES);
    combat_ui_init();
    SPRITEANIM_INIT(&combat_dummy, dummy, TILE_WORLD_SPR, ENEMY_SLOT_TILES);
    combat_events_init();
    combo_reset(&combo);
    combat_want = combat_pending = combat_busy = combat_strike_grace = 0;
    combat_attack = COMBO_NO_ATTACK;
    combat_slowmo = 0;
    slide_left = 0;
    divider = carry_p = carry_d = 0;
    fx_set_dim(0);
    combat_px = PLAYER_START_X << 4;
    combat_py = PLAYER_START_Y << 4;
    px = PLAYER_START_X;
    py = PLAYER_START_Y;

    music_play(BANK(song_combat), &song_combat); /* the clock starts at the first VBlank (scene_show) */
    music_now(&combat_now);
    anim_clock_sync(&clock, &combat_now);
    last_beat = combat_now.beat;
    spriteanim_play(&combat_player, SPRITE_PLAYER_IDLE, FACING_E, &combat_now);
    spriteanim_play(&combat_dummy, SPRITE_DUMMY_IDLE, FACING_S, &combat_now);
    spriteanim_update(&combat_player, 0);
    spriteanim_update(&combat_dummy, 0);
    vram_stream_update(0xFF); /* LCD off: both first frames now */
    vram_stream_vblank(1);
    draw_world();
    overlay_init(OVERLAY_X, OVERLAY_Y);
    scene_show();

    while (1) {
        vsync();
        fx_update(); /* palettes first */
        music_now(&combat_now);
        ticks = anim_clock_ticks(&clock, &combat_now);
        ly = LY_REG;
        late = ly >= LATE_START_LY;
        work = late;

        /* presses -> matcher. A late frame leaves them queued for the next one: their grade was
         * fixed in the ISR; what they show and their musical hit wait (the ISR still holds a hit
         * back for a dodge it saw itself). The frame counter is read
         * before draining (dodge_grace timing); the tick waits while presses are still queued, so
         * it never resolves a held-back A whose B is still in the queue. */
        if (!late) {
            frame = input_frame;
            drained = 1;
            while (1) {
                if (LY_REG >= POP_LIMIT_LY) {
                    drained = 0;
                    break;
                }
                if (!input_pop(&p))
                    break;
                combat_pending_held = p.held;
                combat_pending_heavy = p.buttons & J_B ? 1 : 0;
                combat_popup(p.judgement.grade);
                in.buttons = (p.buttons & J_A ? COMBO_A : 0) | (p.buttons & J_B ? COMBO_B : 0);
                in.dir = combo_dir(p.held);
                in.frame = p.frame;
                in.judgement = p.judgement;
                n = combo_press(&combo, &in, evs);
                schedule_hit();
                handle(n);
            }
            if (drained && LY_REG < TICK_LIMIT_LY) {
                n = combo_tick(&combo, &combat_now, frame, evs);
                schedule_hit();
                handle(n);
                /* a held-back press lands now, so its musical hit is known, unless the player's
                 * hit frame is due this frame too (both together don't fit; it lands next frame,
                 * still within dodge_grace, or when it commits) */
                if (LY_REG < LAND_LIMIT_LY && !hit_frame_due(ticks + carry_p)) {
                    combo_land(&combo);
                    schedule_hit();
                }
            }
        }

        /* The player's attack or dodge first. Its anim then advances from the next frame, with
         * this frame's ticks carried over, so the start costs one anim call, not two. */
        pticks = ticks + carry_p;
        started = 0;
        if (combat_pending && !work && LY_REG < START_LIMIT_LY) {
            start_pending();
            work = started = 1;
        }
        dticks = ticks;
        if (combat_slowmo) { /* the dummy only moves every enemy_divider-th frame */
            if (++divider >= (uint8_t)tuning.slowmo_enemy_divider)
                divider = 0;
            else
                dticks = 0;
        }
        dticks += carry_d;

        /* Anims: at most one new frame shown per video frame, none on a busy one. On a very late
         * frame neither character updates (their ticks carry to the next frame, so they stay on
         * the beat; a hit frame lands one frame later). */
        pev = dev = 0;
        if (started || ly >= VERY_LATE_LY) {
            carry_p = pticks > CARRY_MAX ? CARRY_MAX : pticks;
            carry_d = dticks > CARRY_MAX ? CARRY_MAX : dticks;
        } else {
            carry_p = 0;
            spriteanim_presents = !work && LY_REG < PRESENT_LIMIT_LY;
            pev = spriteanim_update(&combat_player, pticks);
            if (!spriteanim_presents)
                work = 1;
            /* the dummy waits (its ticks carried) when its update would cost a call on a busy frame */
            if (dticks < combat_dummy.anim.quiet || spriteanim_presents || carry_d >= CARRY_MAX) {
                carry_d = 0;
                dev = spriteanim_update(&combat_dummy, dticks);
                if (!spriteanim_presents)
                    work = 1;
            } else {
                carry_d = dticks;
            }
        }
        if (pev & ANIM_EV_HIT) {
            slide_finish();
            px = combat_px >> 4;
            py = combat_py >> 4;
            combat_on_hit_frame();
        }
        if (pev & ANIM_EV_DONE) {
            combat_busy = 0;
            combat_attack = COMBO_NO_ATTACK;
        }
        if (dev & ANIM_EV_DONE)
            combat_want |= WANT_DUMMY_IDLE;

        /* beats and musical timers (cheap, every frame) */
        if (combat_now.beat != last_beat) {
            last_beat = combat_now.beat;
            combat_on_beat();
        }
        if (combat_slowmo) {
            if (ticks >= combat_slowmo) {
                combat_slowmo = 0;
                fx_set_dim(0);
            } else {
                combat_slowmo -= ticks;
            }
        }
        if (combat_strike_grace && --combat_strike_grace == 0)
            combat_strike_lands();

        if (!work && LY_REG < COSTLY_LIMIT_LY)
            work = costly();

        /* movement and UI sprites; a very late frame skips them (they catch up next frame) */
        if (ly < VERY_LATE_LY) {
            solid_bounds();
            if (slide_left) {
                if (!started) /* the lunge or dash moves from the anim's first shown frame */
                    slide_step();
            } else if (!combat_busy) {
                walk();
            }
            px = combat_px >> 4;
            py = combat_py >> 4;
            combat_ui_update(ticks);
        }
        draw_world();
        hud_update();
        if (LY_REG < OVERLAY_LIMIT_LY)
            overlay_update();
        if (!work && LY_REG < TEXT_LIMIT_LY)
            combat_ui_text();

        edges = input_edges();
        if (edges & J_START) {
            vram_stream_vblank(0);
            fx_set_dim(0);
            return SCENE_MENU;
        }
#ifdef DEBUG
        if (edges & J_SELECT)
            overlay_toggle();
#endif

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
    return combat_scene();
}
