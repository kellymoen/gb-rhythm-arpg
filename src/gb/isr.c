#include <gb/gb.h>

#include "audio/music.h"
#include "gb/input.h"
#include "gb/isr.h"
#include "tuning.h"

static void vblank(void)
{
    const press_t *p;

    music_update();
    p = input_poll();
    if (p && tuning.feedback_musical_hits)
        music_hit(p->judgement.slot);
}

void isr_init(void)
{
    CRITICAL {
        add_VBL(vblank);
    }
}
