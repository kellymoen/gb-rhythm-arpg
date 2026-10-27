#ifndef GB_VIDEO_H
#define GB_VIDEO_H

#include <stdint.h>

/* VRAM tile map (shared 0x8000 region, ADR 0001 budgets):
 *   0x00-0x3F  font (BG/window)      0x40-0x7F  UI and world BG tiles
 *   0x80-0xFF  sprite tiles (8x16 sprites use even indices) */
#define TILE_FONT 0x00
#define TILE_UI 0x40
#define TILE_SPRITES 0x80

/* LCD, sprite mode and palettes for both DMG and CGB. Call with the display off. */
void video_init(void);

/* 0 = normal, 1 = one shade lighter (used by the beat pulse). */
void video_set_brightness(uint8_t lighter);

#endif
