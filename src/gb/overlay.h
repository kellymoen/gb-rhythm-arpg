#ifndef GB_OVERLAY_H
#define GB_OVERLAY_H

#include <stdint.h>
#include <gbdk/platform.h>

/* Timing overlay (CONTEXT.md), DEBUG builds only; in release builds the calls compile to nothing.
 *
 * A 32x16 px strip of 4 UI sprites plotting the last OVERLAY_HISTORY press errors as 1x2 px dots,
 * 1 px per frame, centre = on the step slot (left early, right late, clamped at +/-15 frames).
 * The top and bottom rows show the current windows: GOOD light, PERFECT mid, centre dark; dotted
 * guides continue them down the plot. Each press takes the next 2-row slot down, wrapping to the
 * top after the sixth; the newest dot is dark, older ones mid.
 *
 * It reads the DEBUG press log (src/gb/input.h), so it shows exactly what grading saw (after the
 * latency offset) and never takes presses from the scene's queue. Tuning changes to the windows
 * redraw it. Uses sprite tiles 0x88-0x8F and OAM 12-15 (the second half of the UI sprite ranges
 * in video.h), 4 sprites on the same 16 lines.
 *
 * Cost (DMG speed, measured in PyBoy): under 1 scanline on an idle frame, ~7 on a frame with a
 * press, then ~7 on each of the next 1-3 frames while the changed tiles go to VRAM (one per frame). */

#define OVERLAY_HISTORY 6
#define OVERLAY_W 32
#define OVERLAY_H 16

#ifdef DEBUG
/* Show the strip with its top-left at screen pixel (x, y) and forget earlier presses. Sprite
 * mode must be 8x16 (video_init). Visible after init. */
void overlay_init(uint8_t x, uint8_t y) BANKED;

/* Once per main-loop frame, right after vsync() with the other sprite updates. */
void overlay_update(void) BANKED;

/* Hide / show the strip (its history keeps updating while hidden). */
void overlay_toggle(void) BANKED;
#else
#define overlay_init(x, y) ((void)0)
#define overlay_update() ((void)0)
#define overlay_toggle() ((void)0)
#endif

#endif
