#include <gb/gb.h>

#include "audio/music.h"
#include "audio/sfx.h"
#include "gb/input.h"
#include "gb/isr.h"
#include "tuning.h"

/* Audio first (fixed cost at the top of VBlank), then the press, then its musical hit, which starts
 * on the press's own frame. OFFBEAT presses play no hit. */
static void vblank(void)
{
    const press_t *p;

    music_update();
    sfx_update();
    p = input_poll();
    if (p && tuning.feedback_musical_hits && p->judgement.grade != GRADE_OFFBEAT)
        sfx_hit();
}

void isr_init(void)
{
    sfx_init();
    CRITICAL {
        add_VBL(vblank);
    }
}
