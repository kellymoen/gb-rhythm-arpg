#include <gb/gb.h>

#include "gb/input.h"
#include "gb/text.h"
#include "scenes/scene.h"

/* Stub until the calibration package lands (docs/plan.md, M2 package 6). */
scene_t calibrate_run(void)
{
    scene_begin();
    text_print(1, 1, "CALIBRATE");
    text_print(1, 3, "NOT BUILT YET");
    text_print(1, 16, "START: BACK");
    scene_show();
    while (!(input_edges() & J_START))
        vsync();
    return SCENE_MENU;
}
