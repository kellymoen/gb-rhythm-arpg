#ifdef DEBUG

#pragma bank 255

#include <gb/gb.h>
#include <string.h>

#include "gb/input.h"
#include "gb/overlay.h"
#include "gb/video.h"
#include "tuning.h"

/* The second half of the UI sprite range, so grade popups can keep the first half. */
#define OVERLAY_TILE TILE_OVERLAY_SPR
#define OVERLAY_OAM OAM_OVERLAY
#define SPRITES (OVERLAY_W / 8)
#define TILE_BYTES 32 /* one 8x16 sprite: 16 rows of 2 bitplane bytes */

#define CENTRE 15 /* pixel column of a zero error */
#define RANGE 15  /* errors beyond +/- this are drawn at the edge */
#define ROW_BAND_TOP 0
#define ROW_PLOT 2 /* history slots: 2 rows each */
#define ROW_BAND_BOTTOM (OVERLAY_H - 1)

#define DARK 3
#define MID 2
#define LIGHT 1

static uint8_t tmpl[SPRITES * TILE_BYTES]; /* windows only; redrawn when they change */
static uint8_t buf[SPRITES * TILE_BYTES];  /* tmpl + dots: what VRAM gets */
/* History slots form a ring: each press takes the next slot down (wrapping), so a press rewrites
 * 3 slots (the reused one, the new dot, the previous newest) instead of scrolling the image.
 * A slot holds where its dot goes, not its frames, to keep that cheap. */
static uint8_t dot_base[OVERLAY_HISTORY]; /* offset of the dot's sprite in buf: (x / 8) * 32 */
static uint8_t dot_bit[OVERLAY_HISTORY];  /* the dot's bit in its bitplane bytes */
static uint8_t dot_tile[OVERLAY_HISTORY]; /* pending bit of the tile holding the dot */
static uint8_t used, newest;              /* slots in use; slot of the newest press */
static uint8_t seen; /* press_log_head already plotted */
static int16_t shown_perfect, shown_good;
static uint8_t pending; /* bit per tile (sprite * 2 + lower half) still to copy to VRAM */
static uint8_t visible, px, py;

static const uint8_t bits[8] = { 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01 };
static const uint8_t tile_bits[2 * SPRITES] = { 1, 2, 4, 8, 16, 32, 64, 128 };
static const uint8_t slot_at[OVERLAY_HISTORY] = { 4, 8, 12, 16, 20, 24 }; /* 2 * (ROW_PLOT + 2k) */

static void plot(uint8_t *b, uint8_t x, uint8_t row, uint8_t colour)
{
    uint8_t *p = b + (uint8_t)((x & 0xF8) << 2) + (uint8_t)(row << 1);
    uint8_t bit = bits[x & 7];

    if (colour & 1)
        p[0] |= bit;
    else
        p[0] &= ~bit;
    if (colour & 2)
        p[1] |= bit;
    else
        p[1] &= ~bit;
}

static uint8_t clamp_range(int16_t v)
{
    if (v < 0)
        return 0;
    return v > RANGE ? RANGE : (uint8_t)v;
}

static uint8_t column(int8_t frames)
{
    if (frames < -RANGE)
        return CENTRE - RANGE;
    if (frames > RANGE)
        return CENTRE + RANGE;
    return (uint8_t)(CENTRE + frames);
}

static void guide(uint8_t x)
{
    uint8_t row;

    for (row = ROW_PLOT; row < ROW_PLOT + 2 * OVERLAY_HISTORY; row += 2)
        plot(tmpl, x, row, LIGHT);
}

static void draw_template(void)
{
    uint8_t good = clamp_range(tuning.timing_good_window);
    uint8_t perfect = clamp_range(tuning.timing_perfect_window);
    uint8_t x, c, d;

    shown_good = tuning.timing_good_window;
    shown_perfect = tuning.timing_perfect_window;
    memset(tmpl, 0, sizeof tmpl);
    for (x = CENTRE - good; x <= CENTRE + good; x++) {
        d = x < CENTRE ? CENTRE - x : x - CENTRE;
        c = d == 0 ? DARK : d <= perfect ? MID : LIGHT;
        plot(tmpl, x, ROW_BAND_TOP, c);
        plot(tmpl, x, ROW_BAND_BOTTOM, c);
    }
    guide(CENTRE - good);
    guide(CENTRE - perfect);
    guide(CENTRE);
    guide(CENTRE + perfect);
    guide(CENTRE + good);
}


/* Slot k's dot: DARK (both planes) for the newest, MID (high plane only) for older ones. The
 * slot's two rows are bytes p[0..1] and p[2..3], low plane first. */
static void draw_dot(uint8_t k, uint8_t dark)
{
    uint8_t *p = buf + (uint8_t)(dot_base[k] + slot_at[k]), bit = dot_bit[k];

    if (dark) {
        p[0] |= bit;
        p[2] |= bit;
    } else {
        p[0] &= ~bit;
        p[2] &= ~bit;
    }
    p[1] |= bit;
    p[3] |= bit;
    pending |= dot_tile[k];
}

/* Put back the template bytes under slot k's dot. */
static void erase_dot(uint8_t k)
{
    uint8_t off = dot_base[k] + slot_at[k];
    uint8_t *p = buf + off, *t = tmpl + off;

    p[0] = t[0];
    p[1] = t[1];
    p[2] = t[2];
    p[3] = t[3];
    pending |= dot_tile[k];
}

/* Whole image from the template and the history: init and window changes only. */
static void render(void)
{
    uint8_t k;

    memcpy(buf, tmpl, sizeof buf);
    for (k = 0; k < used; k++)
        draw_dot(k, k == newest);
    pending = 0xFF;
}

static void push(int8_t frames)
{
    uint8_t x = column(frames), k = newest + 1;

    if (k == OVERLAY_HISTORY)
        k = 0;
    if (used) {
        draw_dot(newest, 0); /* dim the previous newest */
        if (used == OVERLAY_HISTORY)
            erase_dot(k);
    }
    if (used < OVERLAY_HISTORY)
        used++;
    dot_base[k] = (uint8_t)((x & 0xF8) << 2);
    dot_bit[k] = bits[x & 7];
    /* slots 0-2 sit in a sprite's upper tile (rows 2-7), 3-5 in its lower one (rows 8-13) */
    dot_tile[k] = tile_bits[((x >> 3) << 1) + (k >= 3)];
    newest = k;
    draw_dot(k, 1);
}

static void place(void)
{
    uint8_t i, x = px + DEVICE_SPRITE_PX_OFFSET_X;

    for (i = 0; i < SPRITES; i++, x += 8) {
        if (visible)
            move_sprite(OVERLAY_OAM + i, x, py + DEVICE_SPRITE_PX_OFFSET_Y);
        else
            hide_sprite(OVERLAY_OAM + i);
    }
}

void overlay_init(uint8_t x, uint8_t y) BANKED
{
    uint8_t i;

    seen = press_log_head;
    used = 0;
    newest = OVERLAY_HISTORY - 1; /* the first press goes in the top slot */
    draw_template();
    render();
    set_sprite_data((uint8_t)OVERLAY_TILE, 2 * SPRITES, buf); /* all at once: the LCD is usually off */
    pending = 0;
    for (i = 0; i < SPRITES; i++) {
        set_sprite_tile(OVERLAY_OAM + i, OVERLAY_TILE + 2 * i);
        set_sprite_prop(OVERLAY_OAM + i, 0);
    }
    px = x;
    py = y;
    visible = 1;
    place();
}

void overlay_update(void) BANKED
{
    uint8_t head, t;

    /* Sprite data first, while the frame is young: one changed tile per frame keeps the LCD-on
     * VRAM copy to a few lines (a press changes at most 3 tiles). */
    if (pending) {
        for (t = 0; !(pending & tile_bits[t]); t++)
            ;
        set_sprite_data((uint8_t)(OVERLAY_TILE + t), 1, buf + (uint8_t)(t << 4));
        pending &= ~tile_bits[t];
    }
    if (shown_good != tuning.timing_good_window || shown_perfect != tuning.timing_perfect_window) {
        draw_template();
        render();
    }
    head = press_log_head;
    while (seen != head) {
        push(press_log[seen & (PRESS_LOG_SIZE - 1)].frames);
        seen++;
    }
}

void overlay_toggle(void) BANKED
{
    visible = !visible;
    place();
}

#else
typedef int overlay_disabled_t; /* release builds: keep the translation unit non-empty */
#endif
