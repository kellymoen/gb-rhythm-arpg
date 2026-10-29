#include <gb/gb.h>

#include "audio/music.h"
#include "gb/hud.h"
#include "gb/video.h"
#include "tuning.h"
#include "ui_hud_bar.h"
#include "ui_hud_sprites.h"

#define HUD_Y 136
#define MARKER_X 11       /* screen x of the marker line (window tile 1, columns 3-4) */
#define PIP_CENTRE 3      /* pip centre column inside its sprite */
#define LOOKAHEAD (2 * BEAT_TICKS)

#define TILE_BAR (TILE_UI + 0)
#define TILE_MARKER (TILE_UI + 1)
#define SPR_PIP (TILE_SPRITES + 0)
#define SPR_BEAT_PIP (TILE_SPRITES + 2)

void hud_init(void)
{
    uint8_t row[DEVICE_SCREEN_WIDTH];
    uint8_t i;

    set_bkg_data(TILE_UI, UI_HUD_BAR_TILE_COUNT, ui_hud_bar_tiles);
    set_sprite_data(TILE_SPRITES, UI_HUD_SPRITES_TILE_COUNT, ui_hud_sprites_tiles);
    for (i = 0; i < DEVICE_SCREEN_WIDTH; i++)
        row[i] = TILE_BAR;
    row[1] = TILE_MARKER;
    set_win_tiles(0, 0, DEVICE_SCREEN_WIDTH, 1, row);
    move_win(DEVICE_WINDOW_PX_OFFSET_X, HUD_Y);
    SHOW_WIN;
}

/* Per frame: no divide or multiply helpers (SDCC's 8-bit divide alone costs ~5 scanlines). The slot
 * length is recomputed only when steps_per_beat changes, the slot index by subtraction, and the pips
 * are written straight into shadow OAM. */
void hud_update(void)
{
    static uint8_t spb_seen, slot_ticks;
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    OAM_item_t *o = &shadow_OAM[OAM_HUD];
    beat_clock_t now;
    uint8_t ahead, in_beat, i;

    if (!tuning.feedback_hud_metronome) {
        for (i = 0; i < HUD_PIPS; i++, o++)
            o->y = 0;
        return;
    }
    if (spb != spb_seen) {
        spb_seen = spb;
        slot_ticks = BEAT_TICKS / spb;
    }
    music_now(&now);
    ahead = now.tick;
    in_beat = 1; /* the slot index within the beat of the first pip, 0..spb-1 */
    while (ahead >= slot_ticks) {
        ahead -= slot_ticks;
        in_beat++;
    }
    ahead = slot_ticks - ahead;
    for (i = 0; i < HUD_PIPS; i++, o++) {
        if (ahead > LOOKAHEAD) {
            o->y = 0;
            continue;
        }
        if (in_beat == spb)
            in_beat = 0;
        o->tile = in_beat ? SPR_PIP : SPR_BEAT_PIP;
        o->y = (uint8_t)(DEVICE_SPRITE_PX_OFFSET_Y + HUD_Y);
        o->x = (uint8_t)(DEVICE_SPRITE_PX_OFFSET_X + MARKER_X - PIP_CENTRE) + ahead;
        ahead += slot_ticks;
        in_beat++;
    }
}
