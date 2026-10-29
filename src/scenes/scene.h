#ifndef SCENES_SCENE_H
#define SCENES_SCENE_H

#include <stdint.h>

/* Scenes run one at a time from main(). Each runs until the player leaves it and returns the
 * scene to run next. One file per scene in src/scenes/. */

typedef uint8_t scene_t;
enum { SCENE_MENU, SCENE_COMBAT, SCENE_CALIBRATE, SCENE_RHYTHMTEST, SCENE_COUNT };

/* Call first in every scene: stops the song, turns the LCD off (so VRAM loads are fast), hides
 * the window and every sprite, clears the background and drops queued presses. */
void scene_begin(void);

/* Call once the scene has loaded its VRAM: turns the LCD back on. */
void scene_show(void);

scene_t menu_run(void);
scene_t combat_run(void);     /* src/scenes/combatflat.c */
scene_t calibrate_run(void);
scene_t rhythmtest_run(void);

#endif
