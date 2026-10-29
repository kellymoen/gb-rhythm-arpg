#include <gb/gb.h>

#include "gb/input.h"
#include "gb/text.h"
#include "scenes/scene.h"

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

scene_t menu_run(void)
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
        if (edges & J_UP)
            cursor = cursor ? cursor - 1 : ENTRY_COUNT - 1;
        else if (edges & J_DOWN)
            cursor = cursor + 1 < ENTRY_COUNT ? cursor + 1 : 0;
        else if (edges & (J_A | J_START))
            return entries[cursor].scene;
        if (cursor != old)
            draw_cursor(old);
    }
}
