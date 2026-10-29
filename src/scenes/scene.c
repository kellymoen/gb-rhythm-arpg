#include <gb/gb.h>

#include "audio/music.h"
#include "gb/input.h"
#include "gb/isr.h"
#include "gb/video.h"
#include "scenes/scene.h"

void scene_begin(void)
{
    uint8_t i;

    music_stop();
    DISPLAY_OFF;
    HIDE_WIN;
    for (i = 0; i < MAX_HARDWARE_SPRITES; i++)
        hide_sprite(i);
    fill_bkg_rect(0, 0, DEVICE_SCREEN_BUFFER_WIDTH, DEVICE_SCREEN_BUFFER_HEIGHT, TILE_FONT);
    move_bkg(0, 0);
    video_set_brightness(0);
    input_flush();
    isr_hits_on_press = 0;
    isr_hit_cancel();
}

void scene_show(void)
{
    DISPLAY_ON;
}
