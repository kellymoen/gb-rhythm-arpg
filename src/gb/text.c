#include <gb/gb.h>

#include "gb/text.h"
#include "gb/video.h"
#include "ui_font.h"

#define MAX_COLS 20

static const char symbols[] = "+-.:/!?%><";

static uint8_t glyph(char c)
{
    uint8_t i;

    if (c == ' ')
        return 0;
    if (c >= '0' && c <= '9')
        return 1 + (c - '0');
    if (c >= 'a' && c <= 'z')
        c -= 'a' - 'A';
    if (c >= 'A' && c <= 'Z')
        return 11 + (c - 'A');
    for (i = 0; symbols[i]; i++)
        if (symbols[i] == c)
            return 37 + i;
    return 43; /* '?' */
}

void text_init(void)
{
    set_bkg_data(TILE_FONT, UI_FONT_TILE_COUNT, ui_font_tiles);
}

void text_print(uint8_t x, uint8_t y, const char *s)
{
    uint8_t row[MAX_COLS];
    uint8_t n = 0;

    while (s[n] && n < MAX_COLS) {
        row[n] = TILE_FONT + glyph(s[n]);
        n++;
    }
    if (n)
        set_bkg_tiles(x, y, n, 1, row);
}

/* Digits by repeated subtraction: SDCC's 16-bit divide is far too slow for per-frame use. */
static const uint16_t powers[] = { 10000, 1000, 100, 10, 1 };

void text_print_int(uint8_t x, uint8_t y, int16_t v, uint8_t width, uint8_t sign)
{
    char digits[6], buf[8];
    uint8_t n = 0, i, d, len;
    uint16_t u = v < 0 ? (uint16_t)-v : (uint16_t)v;

    for (i = 0; i < 5; i++) {
        for (d = 0; u >= powers[i]; d++)
            u -= powers[i];
        if (d || n || i == 4)
            digits[n++] = '0' + d;
    }
    len = n + (v < 0 || sign);
    for (i = 0; len + i < width && i < 7 - n; i++)
        buf[i] = ' ';
    if (v < 0)
        buf[i++] = '-';
    else if (sign)
        buf[i++] = '+';
    for (d = 0; d < n; d++)
        buf[i++] = digits[d];
    buf[i] = 0;
    text_print(x, y, buf);
}

void text_clear(uint8_t x, uint8_t y, uint8_t width)
{
    fill_bkg_rect(x, y, width, 1, TILE_FONT);
}
