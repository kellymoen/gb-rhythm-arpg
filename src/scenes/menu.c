#pragma bank 255

#include <gb/gb.h>

#include "audio/sfx.h"
#include "gb/input.h"
#include "gb/text.h"
#include "scenes/scene.h"
#include "sfx.h"

#define ROW_FIRST 4

typedef struct {
    const char *label;
    scene_t scene;
} entry_t;

static const entry_t entries[] = {
    { "COMBAT", SCENE_COMBAT },
    { "CALIBRATE", SCENE_CALIBRATE },
    { "RHYTHM TEST", SCENE_RHYTHMTEST },
};
#define ENTRY_COUNT (sizeof entries / sizeof entries[0])

static uint8_t cursor;

static void draw_cursor(uint8_t old)
{
    text_print(2, ROW_FIRST + old * 2, " ");
    text_print(2, ROW_FIRST + cursor * 2, ">");
}

/* Global, not static: bankpack only assigns a bank to global b_ symbols. */
scene_t menu_scene(void) BANKED;

scene_t menu_scene(void) BANKED
{
    uint8_t i, old, edges;

    scene_begin();
    text_print(4, 1, "BEAT ARPG");
    for (i = 0; i < ENTRY_COUNT; i++)
        text_print(4, ROW_FIRST + i * 2, entries[i].label);
    draw_cursor(cursor);
    scene_show();

    while (1) {
        vsync();
        edges = input_edges();
        old = cursor;
        if (edges & J_UP) {
            cursor = cursor ? cursor - 1 : ENTRY_COUNT - 1;
        } else if (edges & J_DOWN) {
            cursor = cursor + 1 < ENTRY_COUNT ? cursor + 1 : 0;
        } else if (edges & (J_A | J_START)) {
            /* LCD off first (scene_begin would do it next): starting the effect lengthens the
             * VBlank ISR, which would make DISPLAY_OFF miss that VBlank and start every scene a
             * frame late. It starts at the next scene's first VBlank and rings over its start. */
            DISPLAY_OFF;
            sfx_play(SFX_MENU_SELECT);
            return entries[cursor].scene;
        }
        if (cursor != old) {
            sfx_play(SFX_MENU_MOVE);
            draw_cursor(old);
        }
    }
}

/* Bank 0 entry point for main()'s scene table; the menu itself lives in a switchable bank. */
scene_t menu_run(void) NONBANKED
{
    return menu_scene();
}
