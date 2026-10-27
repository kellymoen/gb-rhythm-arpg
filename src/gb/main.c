#include <gb/gb.h>

#include "audio/music.h"
#include "gb/hud.h"
#include "gb/isr.h"
#include "gb/text.h"
#include "gb/video.h"
#include "scenes/rhythmtest.h"
#include "tuning.h"

void main(void)
{
    DISPLAY_OFF;
    tuning_reset();
    video_init();
    text_init();
    hud_init();
    music_init();
    isr_init();
    DISPLAY_ON;

    rhythmtest_run();
}
