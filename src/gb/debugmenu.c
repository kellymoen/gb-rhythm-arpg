#ifdef DEBUG

#include <gb/gb.h>
#include <gbdk/emu_debug.h>

#include "core/beat.h"
#include "gb/debugmenu.h"
#include "gb/text.h"
#include "tuning.h"

typedef struct {
    const char *label; /* 10 columns max */
    const char *toml;  /* key as written in data/tuning.toml */
    int16_t *value;
    int8_t min;
    int8_t max;
} param_t;

static const param_t params[DEBUGMENU_ROWS] = {
    { "LATENCY", "timing.latency_offset", &tuning.timing_latency_offset, -15, 15 },
    { "PERFECT", "timing.perfect_window", &tuning.timing_perfect_window, 0, 10 },
    { "GOOD", "timing.good_window", &tuning.timing_good_window, 0, 20 },
    { "STEPS/BEAT", "timing.steps_per_beat", &tuning.timing_steps_per_beat, 1, 8 },
    { "PULSE", "feedback.palette_pulse", &tuning.feedback_palette_pulse, 0, 2 },
    { "METRONOME", "feedback.hud_metronome", &tuning.feedback_hud_metronome, 0, 1 },
    { "HITS", "feedback.musical_hits", &tuning.feedback_musical_hits, 0, 1 },
};

static uint8_t cursor;

static void draw_row(uint8_t i, uint8_t top)
{
    text_print(0, top + i, i == cursor ? ">" : " ");
    text_clear(1, top + i, 19);
    text_print(1, top + i, params[i].label);
    text_print_int(14, top + i, *params[i].value, 4, params[i].min < 0);
}

void debugmenu_draw(uint8_t top)
{
    uint8_t i;

    for (i = 0; i < DEBUGMENU_ROWS; i++)
        draw_row(i, top);
}

static void change(const param_t *p, int8_t dir)
{
    int16_t v = *p->value + dir;

    /* step slots must divide the beat evenly */
    if (p->value == &tuning.timing_steps_per_beat)
        while (v >= p->min && v <= p->max && BEAT_TICKS % v)
            v += dir;
    if (v >= p->min && v <= p->max)
        *p->value = v;
}

uint8_t debugmenu_update(uint8_t edges, uint8_t top)
{
    uint8_t i, old = cursor;

    if (edges & J_UP)
        cursor = cursor ? cursor - 1 : DEBUGMENU_ROWS - 1;
    else if (edges & J_DOWN)
        cursor = cursor + 1 < DEBUGMENU_ROWS ? cursor + 1 : 0;
    else if (edges & J_LEFT)
        change(&params[cursor], -1);
    else if (edges & J_RIGHT)
        change(&params[cursor], 1);
    else if (edges & J_START) {
        EMU_printf("# tuning values (paste into data/tuning.toml)");
        for (i = 0; i < DEBUGMENU_ROWS; i++)
            EMU_printf("%s = %d", params[i].toml, *params[i].value);
        return 0;
    } else
        return 0;

    draw_row(old, top);
    draw_row(cursor, top);
    return 1;
}

#else
typedef int debugmenu_disabled_t; /* release builds: keep the translation unit non-empty */
#endif
