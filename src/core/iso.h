#ifndef CORE_ISO_H
#define CORE_ISO_H

#include <stdint.h>

/* World coords are subpixels on the ground plane, 16 per pixel (ADR 0003).
 * Keep |wx|, |wy| below 16384 (1024 px) so wx +/- wy fits in int16. */
#define ISO_SUBPX_SHIFT 4

typedef struct {
    int16_t x;
    int16_t y;
} iso_screen_t;

/* 2:1 projection: sx = wx - wy, sy = (wx + wy) / 2, in whole pixels. */
void iso_project(int16_t wx, int16_t wy, iso_screen_t *out);

/* Draw-order key: larger is nearer the camera. */
int16_t iso_depth(int16_t wx, int16_t wy);

#endif
