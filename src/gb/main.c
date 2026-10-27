#include <gb/gb.h>
#include <gb/cgb.h>
#include <stdio.h>

#include "core/iso.h"
#include "tuning.h"

/* M0 hello ROM: proves the toolchain, generated data and portable core link into one ROM. */

static const palette_color_t bg_palette[] = {
    RGB8(232, 240, 216), RGB8(152, 184, 120), RGB8(72, 104, 72), RGB8(16, 32, 32),
};

void main(void)
{
    iso_screen_t s;

    if (_cpu == CGB_TYPE)
        set_bkg_palette(0, 1, bg_palette);

    tuning_reset();
    iso_project(16 << ISO_SUBPX_SHIFT, 0, &s);

    printf("\n  BEAT ARPG  M0\n\n");
    printf("  mode: %s\n", _cpu == CGB_TYPE ? "CGB" : "DMG");
    printf("  perfect +-%d f\n", tuning.timing_perfect_window);
    printf("  good    +-%d f\n", tuning.timing_good_window);
    printf("  iso(16,0)=%d,%d\n", s.x, s.y);

    while (1)
        vsync();
}
