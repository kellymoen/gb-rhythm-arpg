#ifndef GB_DEBUGMENU_H
#define GB_DEBUGMENU_H

#include <stdint.h>

/* DEBUG=1 builds only: live tuning-param editor drawn on BG rows `top`..top+DEBUGMENU_ROWS-1.
 * Up/Down select, Left/Right change, Start dumps every value as tuning.toml lines to the
 * emulator debug console (Emulicious/BGB). */

#define DEBUGMENU_ROWS 7

void debugmenu_draw(uint8_t top);

/* Handle menu buttons from input_edges(). Returns 1 if anything changed (it redraws itself). */
uint8_t debugmenu_update(uint8_t edges, uint8_t top);

#endif
