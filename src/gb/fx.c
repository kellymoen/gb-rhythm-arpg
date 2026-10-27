#include <stdint.h>

#include "audio/music.h"
#include "gb/fx.h"
#include "gb/video.h"
#include "tuning.h"

#define PULSE_FRAMES 3

void fx_update(void)
{
    static uint16_t last_beat = 0xFFFF;
    static uint8_t pulse;
    beat_clock_t now;
    uint16_t beat;
    uint8_t mode = (uint8_t)tuning.feedback_palette_pulse;

    music_now(&now);
    beat = now.beat;
    if (beat != last_beat) {
        last_beat = beat;
        if (mode == 2 || (mode == 1 && beat % music_beats_per_bar == 0)) {
            pulse = PULSE_FRAMES;
            video_set_brightness(1);
        }
    }
    if (pulse && --pulse == 0)
        video_set_brightness(0);
}
