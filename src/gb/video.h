#ifndef GB_VIDEO_H
#define GB_VIDEO_H

#include <stdint.h>

/* VRAM tile map (shared 0x8000 region, ADR 0001 budgets):
 *   0x00-0x3F  font (BG/window)      0x40-0x7F  UI and world BG tiles
 *   0x80-0xFF  sprite tiles (8x16 sprites use even indices) */
#define TILE_FONT 0x00
#define TILE_UI 0x40
#define TILE_SPRITES 0x80

/* Sprite tiles (0x80-0xFF) and OAM entries, split by owner so packages never collide:
 *   tiles 0x80-0x83  HUD metronome pips          OAM 0-7    HUD pips (hud.c)
 *   tiles 0x84-0x87  UI sprites (popups)          OAM 8-11   UI sprites
 *   tiles 0x88-0x8F  DEBUG timing overlay         OAM 12-15  overlay (overlay.c)
 *   tiles 0x90-0xA7  player frame, 2 x 12 tiles   OAM 16-39  world sprites, depth-sorted (oam.c)
 *   tiles 0xA8-0xFF  enemies / dummy / effects                (double-buffered streaming) */
#define TILE_HUD_SPR TILE_SPRITES
#define TILE_UI_SPR 0x84
#define TILE_UI_SPR_COUNT 12
#define TILE_PLAYER_SPR 0x90
#define TILE_WORLD_SPR 0xA8
#define TILE_OVERLAY_SPR 0x88
#define OAM_OVERLAY 12
#define OAM_HUD 0
#define OAM_UI 8
#define OAM_UI_COUNT 8
#define OAM_WORLD 16
#define OAM_WORLD_COUNT 24

/* LCD, sprite mode and palettes for both DMG and CGB. Call with the display off. */
void video_init(void);

/* 0 = normal, 1 = one shade lighter (used by the beat pulse). */
void video_set_brightness(uint8_t lighter);

#endif
