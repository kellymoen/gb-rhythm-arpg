#include <gb/gb.h>

#include "audio/music.h"
#include "audio/sfx.h"
#include "gb/debugmenu.h"
#include "gb/fx.h"
#include "gb/hud.h"
#include "gb/input.h"
#include "gb/isr.h"
#include "gb/text.h"
#include "music.h"
#include "scenes/scene.h"
#include "sfx.h"
#include "tuning.h"

#define ROW_TIME 1
#define ROW_SONG 2
#define ROW_GRADE 3
#define ROW_OFFSET 4
#define ROW_COUNTS 6
#define ROW_SFX 9
#define ROW_BOTTOM 10
#define GRADE_FRAMES 40

/* Audition (D-pad, while the debug menu is closed): Left/Right pick a sound effect, Up plays it,
 * Down switches the song. Their rows are only drawn once used, so the idle screen is unchanged. */
enum { SONG_RHYTHMTEST, SONG_COMBAT, SONG_COUNT };
static const char *const song_names[SONG_COUNT] = { "RHYTHMTEST", "COMBAT    " };
static const char *const sfx_names[SFX_COUNT] = SFX_NAMES;

/* Fixed width so redrawing never needs a separate clear (VRAM writes are slow with the LCD on). */
static const char *const grade_names[] = { "OFFBEAT", "GOOD   ", "PERFECT" };
static uint16_t counts[3];
static uint8_t count_dirty; /* bit per grade; drawn a frame later to spread VRAM writes */
static uint16_t bar;
static uint8_t beat_in_bar;
static uint8_t song;
static uint8_t sfx_sel;
static uint8_t shown_bpm;

static void draw_help(void)
{
    uint8_t y;

    for (y = ROW_BOTTOM; y < ROW_BOTTOM + 7; y++)
        text_clear(0, y, 20);
    text_print(1, ROW_BOTTOM, "PRESS A OR B");
    text_print(1, ROW_BOTTOM + 1, "ON THE BEAT");
    text_print(1, ROW_BOTTOM + 6, "START: BACK");
#ifdef DEBUG
    text_print(1, ROW_BOTTOM + 3, "SELECT: TUNING");
    text_print(1, ROW_BOTTOM + 4, "L/R/UP: SFX");
    text_print(1, ROW_BOTTOM + 5, "DOWN: SONG");
#endif
}

static void draw_count(uint8_t g)
{
    text_print_int(10, ROW_COUNTS + 2 - g, (int16_t)counts[g], 5, 0);
}

static void draw_labels(void)
{
    uint8_t g;

    text_print(1, 0, "RHYTHM TEST");
    text_print(1, ROW_TIME, "BPM");
    shown_bpm = (uint8_t)music_bpm;
    text_print_int(5, ROW_TIME, shown_bpm, 3, 0);
    text_print(10, ROW_TIME, "BAR");
    text_print(17, ROW_TIME, ":");
    for (g = 0; g < 3; g++) {
        text_print(1, ROW_COUNTS + 2 - g, grade_names[g]);
        draw_count(g);
    }
}

static void play_song(void)
{
    if (song == SONG_COMBAT)
        music_play(BANK(song_combat), &song_combat);
    else
        music_play(BANK(song_rhythmtest), &song_rhythmtest);
    bar = 1;
    beat_in_bar = 0;
}

static void draw_sfx(void)
{
    text_print(1, ROW_SFX, "SFX");
    text_clear(5, ROW_SFX, 13);
    text_print(5, ROW_SFX, sfx_names[sfx_sel]);
}

/* A run of on-beat presses plays rising HITS pitches, like a combo string; an OFFBEAT press or two
 * silent beats end the run. Each press plays its hit at once (isr_hits_on_press); the combat scene
 * schedules the hit of the combo step a press became instead. */
static void next_hit_step(const press_t *p)
{
    if (p->judgement.grade == GRADE_OFFBEAT || ++sfx_hit_step >= music_hit_count)
        sfx_hit_step = 0;
}

/* A press is drawn over three frames, one print each: on a press frame the ISR is at its busiest
 * (song events, musical hit, maybe an effect starting). */
static int8_t press_frames;
static uint8_t press_stage; /* text jobs left for the last press: 2 = offset, 1 = early/late */

static void show_press(const press_t *p)
{
    press_frames = p->judgement.frames;
    counts[p->judgement.grade]++;
    count_dirty |= 1 << p->judgement.grade;
    text_print(1, ROW_GRADE, grade_names[p->judgement.grade]);
    press_stage = 2;
}

static void show_press_offset(void)
{
    if (press_stage == 2)
        text_print_int(1, ROW_OFFSET, press_frames, 3, 1);
    else
        text_print(5, ROW_OFFSET, press_frames < 0 ? "F EARLY" : press_frames > 0 ? "F LATE " : "F      ");
    press_stage--;
}

/* Counted incrementally once per beat change, avoiding a 16-bit divide by beats_per_bar. */
static void draw_time(void)
{
    if (++beat_in_bar > music_beats_per_bar) {
        beat_in_bar = 1;
        bar++;
    }
    text_print_int(14, ROW_TIME, (int16_t)bar, 3, 0);
    text_print_int(18, ROW_TIME, beat_in_bar, 1, 0);
}

scene_t rhythmtest_run(void)
{
    press_t press;
    beat_clock_t now;
    uint16_t last_beat = 0xFFFF, last_press_beat = 0;
    uint8_t grade_timer = 0, time_dirty = 0, sfx_dirty = 0, song_dirty = 0, bpm_dirty = 0, edges, g;
#ifdef DEBUG
    uint8_t menu = 0;
#endif

    scene_begin();
    counts[0] = counts[1] = counts[2] = 0;
    count_dirty = 0;
    sfx_hit_step = 0;
    isr_hits_on_press = 1;
    press_stage = 0;
    song = SONG_RHYTHMTEST;
    hud_init();
    play_song(); /* the clock waits for VBlank, i.e. scene_show */
    draw_labels();
    draw_help();
    scene_show();

    while (1) {
        vsync();
        /* Sprite/palette updates first so they always land this frame; text may spill over. */
        hud_update();
        fx_update();

        music_now(&now);
        if (now.beat != last_beat) {
            last_beat = now.beat;
            time_dirty = 1;
            if ((uint8_t)music_bpm != shown_bpm)
                bpm_dirty = 1;
            if ((uint16_t)(now.beat - last_press_beat) >= 2)
                sfx_hit_step = 0;
        }
        if (grade_timer > 1) /* holds at 1 until the clear below gets its frame */
            grade_timer--;

        /* At most one text job per frame: VRAM writes with the LCD on are slow. */
        if (press_stage) {
            show_press_offset();
        } else if (count_dirty) {
            for (g = 0; g < 3; g++)
                if (count_dirty & (1 << g))
                    draw_count(g);
            count_dirty = 0;
        } else if (input_pop(&press)) {
            next_hit_step(&press);
            last_press_beat = now.beat;
            show_press(&press);
            grade_timer = GRADE_FRAMES;
        } else if (time_dirty) {
            draw_time();
            time_dirty = 0;
        } else if (bpm_dirty) {
            shown_bpm = (uint8_t)music_bpm;
            text_print_int(5, ROW_TIME, shown_bpm, 3, 0);
            bpm_dirty = 0;
        } else if (sfx_dirty) {
            draw_sfx();
            sfx_dirty = 0;
        } else if (song_dirty) {
            text_print(1, ROW_SONG, "SONG");
            text_print(6, ROW_SONG, song_names[song]);
            song_dirty = 0;
        } else if (grade_timer == 1) {
            text_clear(1, ROW_GRADE, 7);
            text_clear(1, ROW_OFFSET, 11);
            grade_timer = 0;
        }

        edges = input_edges();
#ifdef DEBUG
        if (edges & J_SELECT) {
            menu = !menu;
            if (menu)
                debugmenu_draw(ROW_BOTTOM);
            else
                draw_help();
        } else if (menu) {
            debugmenu_update(edges, ROW_BOTTOM);
            continue; /* Start dumps values while the menu is open */
        }
#endif
        if (edges & (J_LEFT | J_RIGHT)) {
            if (edges & J_LEFT)
                sfx_sel = sfx_sel ? sfx_sel - 1 : SFX_COUNT - 1;
            else
                sfx_sel = sfx_sel + 1 < SFX_COUNT ? sfx_sel + 1 : 0;
            sfx_dirty = 1;
        }
        if (edges & J_UP) {
            sfx_play(sfx_sel);
            sfx_dirty = 1;
        }
        if (edges & J_DOWN) {
            song = song + 1 < SONG_COUNT ? song + 1 : 0;
            play_song();
            last_beat = 0xFFFF;
            last_press_beat = 0;
            song_dirty = bpm_dirty = 1;
        }
        if (edges & J_START) {
            isr_hits_on_press = 0;
            return SCENE_MENU;
        }
    }
}
