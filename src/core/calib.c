#ifdef __SDCC
#pragma bank 255
#endif

#include "core/calib.h"

void calib_reset(calib_t *c) CALIB_FN
{
    c->count = 0;
}

uint8_t calib_add(calib_t *c, int8_t frames) CALIB_FN
{
    uint8_t j;

    if (c->count < CALIB_TAPS) {
        c->err[c->count] = frames;
        for (j = c->count; j > 0 && c->sorted[j - 1] > frames; j--)
            c->sorted[j] = c->sorted[j - 1];
        c->sorted[j] = frames;
        c->count++;
    }
    return c->count == CALIB_TAPS;
}

void calib_result(const calib_t *c, calib_result_t *r) CALIB_FN
{
    const int8_t *s = c->sorted;
    uint8_t n = c->count, mid;
    int16_t sum;

    r->median = 0;
    r->spread = 0;
    r->offset = 0;
    if (!n)
        return;

    mid = n >> 1;
    if (n & 1) {
        r->median = s[mid];
    } else {
        sum = (int16_t)s[mid - 1] + s[mid];
        r->median = (int8_t)(sum >= 0 ? (sum + 1) >> 1 : -((1 - sum) >> 1));
    }
    r->spread = (uint8_t)(s[n - 1 - (n >> 2)] - s[n >> 2]);

    r->offset = r->median;
    if (r->offset < CALIB_OFFSET_MIN)
        r->offset = CALIB_OFFSET_MIN;
    else if (r->offset > CALIB_OFFSET_MAX)
        r->offset = CALIB_OFFSET_MAX;
}
