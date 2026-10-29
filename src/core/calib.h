#ifndef CORE_CALIB_H
#define CORE_CALIB_H

#include <stdint.h>

/* Calibration maths (CONTEXT.md "Calibration"): the player taps on the beat, each tap's raw frame
 * error (judged with no latency offset) is collected, and the median error becomes the latency
 * offset. Portable C99: runs on the ROM once per calibration and on the host in tests/host. */

/* Runs once per tap at most, so under SDCC it lives in a switchable bank (bank 0 is scarce) and is
 * called with banked calls. (A compiler attribute, not a GBDK header: the host build ignores it.) */
#ifdef __SDCC
#define CALIB_FN __banked
#else
#define CALIB_FN
#endif

#define CALIB_TAPS 16 /* PROVISIONAL: taps per calibration run */

/* Range of tuning timing.latency_offset (data/tuning.toml says [-15..15]). */
#define CALIB_OFFSET_MIN (-15)
#define CALIB_OFFSET_MAX 15

typedef struct {
    int8_t err[CALIB_TAPS];    /* raw frame error per tap, in tap order: < 0 early, > 0 late */
    int8_t sorted[CALIB_TAPS]; /* the same, kept sorted as taps arrive */
    uint8_t count;
} calib_t;

typedef struct {
    int8_t median; /* median error; with an even count, the mean of the middle two, rounded away from 0 */
    uint8_t spread; /* width of the middle half of the sorted errors, in frames */
    int8_t offset;  /* median clamped to [CALIB_OFFSET_MIN..CALIB_OFFSET_MAX]: the new latency offset */
} calib_result_t;

void calib_reset(calib_t *c) CALIB_FN;

/* Record one tap (one insertion step, so no frame pays for a whole sort). Taps past CALIB_TAPS
 * are ignored. Returns 1 once the run is complete. */
uint8_t calib_add(calib_t *c, int8_t frames) CALIB_FN;

/* Median, spread and offset of the taps so far (all zero with no taps). */
void calib_result(const calib_t *c, calib_result_t *r) CALIB_FN;

#endif
