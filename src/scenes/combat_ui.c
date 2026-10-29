#pragma bank 255

#include <gb/gb.h>
#include <gb/cgb.h>

#include "core/combo.h"
#include "gb/text.h"
#include "gb/vram_stream.h"
#include "scenes/combat.h"
#include "tuning.h"
#include "ui_floor.h"
#include "ui_popups_sprites.h"

/* Combat scene UI (combat.h): grade popups, the dummy's "!" telegraph and strike mark, its hit
 * flash, the floor and the text counters. All PROVISIONAL.
 *
 * assets/ui/popups_sprites.png contract: four 16x16 cells of 8x16 sprites, left to right PERFECT,
 * GOOD, OFF (offbeat), then "!" (left half) and the strike mark (right half). A popup's cell is
 * streamed into TILE_POPUP_SPR when it changes (64 bytes, after the player's frames); the popup
 * stays hidden until the copy is done, so a half-copied word never shows. */

#define CELL_TILES 4
#define CELL_FX 3
#define POPUP_ABOVE 46     /* popup top, px above the player's feet */
#define TELEGRAPH_ABOVE 46 /* "!" top, px above the dummy's feet */

/* Hit flash: the dummy's parts switch to the second OBJ palette (DMG OBP1, CGB OBJ palette 1),
 * in which colours 1-2 are white and the outline stays dark. Both bits are set: each machine
 * ignores the other's. */
#define FLASH_PROPS 0x11
#define FLASH_DMG 0xC0
static const palette_color_t flash_cgb[] = {
    RGB8(232, 240, 216), RGB8(255, 255, 255), RGB8(255, 255, 255), RGB8(16, 32, 32),
};

#define FLOOR_TOP 2     /* BG rows: 0-1 counters, 2-16 floor, 17 the HUD window */
#define FLOOR_BOTTOM 16

#define JOB_DMG 0x01
#define JOB_HITS 0x02
#define JOB_NAME 0x04
#define NAME_W 16

static vram_job_t popup_job;
static uint8_t popup_cell, popup_ready, popup_on, popup_x, popup_y, popup_rise;
static uint16_t popup_age, popup_rise_ticks;
static uint8_t telegraph_on, strike_on, strike_x, strike_y;
static uint16_t strike_age;
static uint8_t flash_ticks;
/* Shadow OAM is only written when a sprite moves, appears or disappears: most frames touch nothing. */
static uint8_t popup_shown_y, telegraph_shown, strike_shown;
static uint8_t jobs, name;

/* COMBO_STRING_* order (data/combos.toml); others print as COMBO. */
static const char *const string_names[] = { "RUSH", "PAUSE", "CRUSH", "CRUSH LUNGE" };
#define STRING_NAMES (sizeof string_names / sizeof string_names[0])
static const char *const other_names[] = { "BREAK", "DODGE", "PERFECT DODGE", "OUCH", "DODGED!", "" };

void combat_ui_init(void) BANKED
{
    uint8_t row[DEVICE_SCREEN_WIDTH], x, y;

    vram_copy_tiles(TILE_FX_SPR, BANK(ui_popups_sprites), ui_popups_sprites_tiles + CELL_FX * CELL_TILES * 16,
                    CELL_TILES);
    vram_copy_tiles(TILE_FLOOR, BANK(ui_floor), ui_floor_tiles, UI_FLOOR_TILE_COUNT);
    for (y = FLOOR_TOP; y <= FLOOR_BOTTOM; y++) {
        for (x = 0; x < DEVICE_SCREEN_WIDTH; x++)
            row[x] = TILE_FLOOR + (((y - FLOOR_TOP) & 1) << 2) + (x & 3);
        set_bkg_tiles(0, y, DEVICE_SCREEN_WIDTH, 1, row);
    }
    OBP1_REG = FLASH_DMG;
    if (_cpu == CGB_TYPE)
        set_sprite_palette(1, 1, flash_cgb);

    popup_job.state = VJ_IDLE;
    vram_stream_add(&popup_job);
    popup_cell = 0xFF;
    popup_ready = popup_on = telegraph_on = strike_on = flash_ticks = 0;
    popup_shown_y = telegraph_shown = strike_shown = 0;
    set_sprite_tile(OAM_POPUP, TILE_POPUP_SPR);
    set_sprite_tile(OAM_POPUP + 1, (uint8_t)(TILE_POPUP_SPR + 2));
    set_sprite_tile(OAM_TELEGRAPH, TILE_FX_SPR);
    set_sprite_tile(OAM_STRIKE, (uint8_t)(TILE_FX_SPR + 2));

    text_print(0, 0, "DMG");
    text_print(10, 0, "HIT");
    text_print_int(4, 0, 0, 5, 0);
    text_print_int(14, 0, 0, 2, 0);
    text_print(0, 1, "READY");
    jobs = 0;
}

void combat_popup(uint8_t grade) BANKED
{
    uint8_t cell;

    if (!tuning.feedback_grade_popups)
        return;
    cell = grade == GRADE_PERFECT ? 0 : grade == GRADE_GOOD ? 1 : 2;
    if (cell != popup_cell) {
        popup_cell = cell;
        popup_ready = 0;
        vram_stream_submit(&popup_job, BANK(ui_popups_sprites),
                           ui_popups_sprites_tiles + ((uint16_t)cell << 6), TILE_POPUP_SPR, CELL_TILES);
    }
    popup_on = 1;
    popup_age = 0;
    popup_rise = popup_rise_ticks = 0;
    popup_x = (uint8_t)((combat_px >> 4) - 8);
    popup_y = (uint8_t)((combat_py >> 4) - POPUP_ABOVE);
}

void combat_telegraph(uint8_t on) BANKED
{
    telegraph_on = on;
}

void combat_strike_mark(int16_t x, int16_t y) BANKED
{
    strike_on = 1;
    strike_shown = 0; /* (re)place it */
    strike_age = 0;
    strike_x = (uint8_t)(x - 4);
    strike_y = (uint8_t)(y - 8);
}

void combat_flash(void) BANKED
{
    if (tuning.feedback_hit_flash)
        flash_ticks = (uint8_t)tuning.feedback_hit_flash_ticks;
}

/* Set or clear the flash palette on both of the dummy's slots (show_frame recopies a slot's parts
 * from ROM, so this runs every frame while the flash lasts). */
static void flash_props(uint8_t on)
{
    metasprite_t *m;
    uint8_t s, n;

    for (s = 0; s < 2; s++) {
        m = combat_dummy.slot[s].parts;
        for (n = combat_dummy.slot[s].look.count; n; n--, m++)
            m->props = on ? m->props | FLASH_PROPS : m->props & (uint8_t)~FLASH_PROPS;
    }
}

void combat_ui_update(uint8_t ticks) BANKED
{
    uint8_t y, show, rise;

    if (popup_job.state == VJ_READY) {
        popup_job.state = VJ_IDLE;
        popup_ready = 1;
    }
    y = 0;
    if (popup_on) {
        popup_age += ticks;
        /* rises 1 px every feedback.popup_rise_ticks song ticks, counted by subtraction */
        rise = (uint8_t)tuning.feedback_popup_rise_ticks;
        popup_rise_ticks += ticks;
        while (rise && popup_rise_ticks >= rise) {
            popup_rise_ticks -= rise;
            popup_rise++;
        }
        if (popup_age >= (uint16_t)tuning.feedback_popup_ticks)
            popup_on = 0;
        else if (popup_ready)
            y = popup_y - popup_rise + DEVICE_SPRITE_PX_OFFSET_Y;
    }
    if (y != popup_shown_y) {
        popup_shown_y = y;
        if (y) {
            move_sprite(OAM_POPUP, popup_x + DEVICE_SPRITE_PX_OFFSET_X, y);
            move_sprite(OAM_POPUP + 1, popup_x + DEVICE_SPRITE_PX_OFFSET_X + 8, y);
        } else {
            hide_sprite(OAM_POPUP);
            hide_sprite(OAM_POPUP + 1);
        }
    }

    show = telegraph_on && combat_now.tick < (uint8_t)tuning.dummy_telegraph_blink_ticks;
    if (show != telegraph_shown) {
        telegraph_shown = show;
        if (show)
            move_sprite(OAM_TELEGRAPH, DUMMY_X - 4 + DEVICE_SPRITE_PX_OFFSET_X,
                        DUMMY_Y - TELEGRAPH_ABOVE + DEVICE_SPRITE_PX_OFFSET_Y);
        else
            hide_sprite(OAM_TELEGRAPH);
    }

    if (strike_on) {
        strike_age += ticks;
        if (strike_age >= (uint16_t)tuning.feedback_popup_ticks)
            strike_on = 0;
    }
    if (strike_on != strike_shown) {
        strike_shown = strike_on;
        if (strike_on)
            move_sprite(OAM_STRIKE, strike_x + DEVICE_SPRITE_PX_OFFSET_X, strike_y + DEVICE_SPRITE_PX_OFFSET_Y);
        else
            hide_sprite(OAM_STRIKE);
    }

    if (flash_ticks) {
        flash_ticks = ticks >= flash_ticks ? 0 : flash_ticks - ticks;
        flash_props(flash_ticks != 0);
    }
}

void combat_ui_name(uint8_t n) BANKED
{
    name = n;
    jobs |= JOB_NAME;
}

void combat_ui_counters(void) BANKED
{
    jobs |= JOB_DMG | JOB_HITS;
}

uint8_t combat_ui_text(void) BANKED
{
    char line[NAME_W + 1];
    const char *s;
    uint8_t i;
    uint16_t d;

    if (jobs & JOB_DMG) {
        jobs &= (uint8_t)~JOB_DMG;
        d = combat_stats.damage;
        text_print_int(4, 0, (int16_t)(d > 32767 ? 32767 : d), 5, 0);
        return 1;
    }
    if (jobs & JOB_HITS) {
        jobs &= (uint8_t)~JOB_HITS;
        text_print_int(14, 0, combat_stats.hits, 2, 0);
        return 1;
    }
    if (jobs & JOB_NAME) {
        jobs &= (uint8_t)~JOB_NAME;
        if (name < STRING_NAMES)
            s = string_names[name];
        else if (name >= NAME_BREAK && name <= NAME_BLANK)
            s = other_names[name - NAME_BREAK];
        else
            s = "COMBO";
        for (i = 0; i < NAME_W && s[i]; i++)
            line[i] = s[i];
        for (; i < NAME_W; i++)
            line[i] = ' ';
        line[NAME_W] = 0;
        text_print(0, 1, line);
        return 1;
    }
    return 0;
}
