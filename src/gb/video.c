#include <gb/gb.h>
#include <gb/cgb.h>

#include "gb/video.h"

/* Placeholder palette until assets/palettes.aseprite exists (M2). */
static const palette_color_t normal[] = {
    RGB8(232, 240, 216), RGB8(152, 184, 120), RGB8(72, 104, 72), RGB8(16, 32, 32),
};
static const palette_color_t light[] = {
    RGB8(248, 252, 240), RGB8(232, 240, 216), RGB8(152, 184, 120), RGB8(72, 104, 72),
};
static const palette_color_t dark[] = {
    RGB8(232, 240, 216), RGB8(72, 104, 72), RGB8(16, 32, 32), RGB8(16, 32, 32),
};

#define DMG_NORMAL 0xE4 /* index n -> shade n */
#define DMG_LIGHT 0x90  /* each index one shade lighter */
#define DMG_DARK 0xF8   /* colours 1-3 one shade darker; 0 (the floor, behind sprites) stays */

void video_init(void)
{
    LCDC_REG |= LCDCF_BG8000;
    SPRITES_8x16;
    BGP_REG = DMG_NORMAL;
    OBP0_REG = DMG_NORMAL;
    if (_cpu == CGB_TYPE) {
        set_bkg_palette(0, 1, normal);
        set_sprite_palette(0, 1, normal);
    }
    fill_bkg_rect(0, 0, DEVICE_SCREEN_BUFFER_WIDTH, DEVICE_SCREEN_BUFFER_HEIGHT, TILE_FONT);
    SHOW_BKG;
    SHOW_SPRITES;
}

void video_set_brightness(uint8_t level)
{
    BGP_REG = level == BRIGHTNESS_PULSE ? DMG_LIGHT : level == BRIGHTNESS_DIM ? DMG_DARK : DMG_NORMAL;
    if (_cpu == CGB_TYPE)
        set_bkg_palette(0, 1, level == BRIGHTNESS_PULSE ? light : level == BRIGHTNESS_DIM ? dark : normal);
}
