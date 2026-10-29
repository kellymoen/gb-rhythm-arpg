#ifndef GB_DEBUGMENU_H
#define GB_DEBUGMENU_H

#include <gbdk/platform.h>
#include <stdint.h>

/* DEBUG=1 builds only: live editor for every tuning param (ADR 0004), generated from data/tuning.toml
 * by tools/gbtools/tuning.py. Drawn on BG rows top..top+DEBUGMENU_ROWS-1, full screen width:
 *   row 0     page title: the TOML [table], plus "n/m" when the table needs more than one page
 *   rows 1-6  one param each: cursor, label (key or its {LABEL} override), value
 *
 * Controls: Up/Down select a param (wraps), Left/Right change it by 1 within its range (steps_per_beat
 * skips values that don't divide the beat), A next page, B previous page, Start dumps every value as
 * tuning.toml lines to the emulator debug console (Emulicious/BGB). The caller decides what opens and
 * closes the menu (rhythmtest: Select).
 *
 * Text: the menu writes at most one row per call (one BG text job, docs/perf.md), so the caller calls
 * debugmenu_draw() once to show it and debugmenu_update() every frame while it is shown; the rows
 * appear over the next DEBUGMENU_ROWS frames. Page, cursor and values persist while it is closed. */

#define DEBUGMENU_ROWS 7

/* Show the menu at `top`: queues every row; draws nothing this call. */
void debugmenu_draw(uint8_t top) BANKED;

/* Handle buttons from input_edges(), then draw at most one queued row. Returns 1 if it drew one (this
 * frame's text job is used). */
uint8_t debugmenu_update(uint8_t edges, uint8_t top) BANKED;

#endif
