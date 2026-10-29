#pragma bank 255

#include <stdint.h>

#include "audio/music.h"
#include "gb/fx.h"
#include "gb/video.h"
#include "tuning.h"

#define PULSE_FRAMES 3

static uint16_t last_beat = 0xFFFF;
static uint8_t in_bar; /* beats since the bar's downbeat, counted up: no per-frame modulo */
static uint8_t pulse, base, shown;

void fx_set_dim(uint8_t on) BANKED
{
    base = on ? BRIGHTNESS_DIM : BRIGHTNESS_NORMAL;
}

void fx_update(void) BANKED
{
    beat_clock_t now;
    uint16_t beat;
    uint8_t mode = (uint8_t)tuning.feedback_palette_pulse, level, b;

    music_now(&now);
    beat = now.beat;
    if (beat != last_beat) {
        if (beat == last_beat + 1) {
            if (++in_bar >= music_beats_per_bar)
                in_bar = 0;
        } else { /* first beat seen, or the song (re)started: count from the start */
            b = beat < 0x100 ? (uint8_t)beat : 0;
            while (music_beats_per_bar && b >= music_beats_per_bar)
                b -= music_beats_per_bar;
            in_bar = b;
        }
        last_beat = beat;
        if (mode == 2 || (mode == 1 && in_bar == 0))
            pulse = PULSE_FRAMES;
    }
    level = base;
    if (pulse) {
        pulse--;
        level = BRIGHTNESS_PULSE;
    }
    if (level != shown) {
        shown = level;
        video_set_brightness(level);
    }
}
