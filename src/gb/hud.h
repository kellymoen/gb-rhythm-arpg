#ifndef GB_HUD_H
#define GB_HUD_H

/* Window-layer HUD: an 8px metronome bar at the bottom of the screen. Upcoming step slots slide
 * left toward the hit marker at 1 px per song tick; beats show as big pips, off-beats as small. */

void hud_init(void);

/* Once per main-loop frame. Uses OAM sprites 0..HUD_PIPS-1. */
void hud_update(void);

#define HUD_PIPS 8

#endif
