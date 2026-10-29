#include <gb/gb.h>

#include "audio/music.h"
#include "gb/isr.h"
#include "gb/text.h"
#include "gb/video.h"
#include "scenes/scene.h"
#include "tuning.h"

typedef scene_t (*scene_fn)(void);

static const scene_fn scenes[SCENE_COUNT] = {
    menu_run,
    combat_run,
    calibrate_run,
    rhythmtest_run,
};

void main(void)
{
    scene_t scene = SCENE_MENU;

    DISPLAY_OFF;
    tuning_reset();
    video_init();
    text_init();
    music_init();
    isr_init();
    DISPLAY_ON;

    while (1)
        scene = scenes[scene]();
}
