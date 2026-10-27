#include "core/iso.h"

/* Relies on arithmetic right shift of negative values (true for SDCC and clang). */
void iso_project(int16_t wx, int16_t wy, iso_screen_t *out)
{
    out->x = (int16_t)(wx - wy) >> ISO_SUBPX_SHIFT;
    out->y = (int16_t)(wx + wy) >> (ISO_SUBPX_SHIFT + 1);
}

int16_t iso_depth(int16_t wx, int16_t wy)
{
    return wx + wy;
}
