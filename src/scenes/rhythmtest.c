#include <gb/gb.h>

#include "audio/music.h"
#include "gb/debugmenu.h"
#include "gb/fx.h"
#include "gb/hud.h"
#include "gb/input.h"
#include "gb/text.h"
#include "music.h"
#include "scenes/scene.h"
#include "tuning.h"

#define ROW_TIME 1
#define ROW_GRADE 3
#define ROW_OFFSET 4
#define ROW_COUNTS 6
#define ROW_BOTTOM 10
#define GRADE_FRAMES 40

/* Fixed width so redrawing never needs a separate clear (VRAM writes are slow with the LCD on). */
static const char *const grade_names[] = { "OFFBEAT", "GOOD   ", "PERFECT" };
static uint16_t counts[3];
static uint8_t count_dirty; /* bit per grade; drawn a frame later to spread VRAM writes */
static uint16_t bar;
static uint8_t beat_in_bar;

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
    text_print_int(5, ROW_TIME, (int16_t)music_bpm, 3, 0);
    text_print(10, ROW_TIME, "BAR");
    text_print(17, ROW_TIME, ":");
    for (g = 0; g < 3; g++) {
        text_print(1, ROW_COUNTS + 2 - g, grade_names[g]);
        draw_count(g);
    }
}

static void show_press(const press_t *p)
{
    int8_t f = p->judgement.frames;

    counts[p->judgement.grade]++;
    count_dirty |= 1 << p->judgement.grade;
    text_print(1, ROW_GRADE, grade_names[p->judgement.grade]);
    text_print_int(1, ROW_OFFSET, f, 3, 1);
    text_print(5, ROW_OFFSET, f < 0 ? "F EARLY" : f > 0 ? "F LATE " : "F      ");
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
    uint16_t last_beat = 0xFFFF;
    uint8_t grade_timer = 0, time_dirty = 0, edges, g;
#ifdef DEBUG
    uint8_t menu = 0;
#endif

    scene_begin();
    counts[0] = counts[1] = counts[2] = 0;
    count_dirty = 0;
    bar = 1;
    beat_in_bar = 0;
    hud_init();
    music_play(BANK(song_rhythmtest), &song_rhythmtest); /* the clock waits for VBlank, i.e. scene_show */
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
        }
        if (grade_timer > 1) /* holds at 1 until the clear below gets its frame */
            grade_timer--;

        /* At most one text job per frame: VRAM writes with the LCD on are slow. */
        if (count_dirty) {
            for (g = 0; g < 3; g++)
                if (count_dirty & (1 << g))
                    draw_count(g);
            count_dirty = 0;
        } else if (input_pop(&press)) {
            show_press(&press);
            grade_timer = GRADE_FRAMES;
        } else if (time_dirty) {
            draw_time();
            time_dirty = 0;
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
        if (edges & J_START)
            return SCENE_MENU;
    }
}
