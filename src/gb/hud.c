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

void hud_update(void)
{
    uint8_t spb = (uint8_t)tuning.timing_steps_per_beat;
    uint8_t slot_ticks = BEAT_TICKS / spb; /* the only division: per-pip math is additions */
    beat_clock_t now;
    uint8_t ahead, in_beat, i;

    music_now(&now);
    in_beat = now.tick / slot_ticks;                /* slot index within the beat, 0..spb-1 */
    ahead = slot_ticks - (now.tick - in_beat * slot_ticks);
    in_beat++;
    for (i = 0; i < HUD_PIPS; i++) {
        if (!tuning.feedback_hud_metronome || ahead > LOOKAHEAD) {
            hide_sprite(i);
            continue;
        }
        if (in_beat == spb)
            in_beat = 0;
        set_sprite_tile(i, in_beat ? SPR_PIP : SPR_BEAT_PIP);
        move_sprite(i, (uint8_t)(DEVICE_SPRITE_PX_OFFSET_X + MARKER_X - PIP_CENTRE) + ahead,
                    (uint8_t)(DEVICE_SPRITE_PX_OFFSET_Y + HUD_Y));
        ahead += slot_ticks;
        in_beat++;
    }
}
