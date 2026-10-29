#ifndef GB_FX_H
#define GB_FX_H

#include <gbdk/platform.h>
#include <stdint.h>

/* Beat feedback effects on the background palette: the palette pulse (tuning feedback.palette_pulse)
 * and the slow-mo dim. Palette writes happen in fx_update(), so call it first thing after vsync(). */
void fx_update(void) BANKED;

/* Slow-mo cue: the background's colours 1-3 one shade darker (the floor lines stand out) from the
 * next fx_update() until turned off; the palette pulse still flashes over it. Scenes that use it turn
 * it off when they end. */
void fx_set_dim(uint8_t on) BANKED;

#endif
