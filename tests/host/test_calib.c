#include "test.h"
#include "core/calib.h"

static void run(calib_t *c, const int8_t *taps, unsigned n, calib_result_t *r)
{
    unsigned i;

    calib_reset(c);
    for (i = 0; i < n; i++)
        calib_add(c, taps[i]);
    calib_result(c, r);
}

void test_calib(void)
{
    calib_t c;
    calib_result_t r;
    unsigned i;

    /* Consistently 3 frames late, with two wild taps that the median ignores. */
    {
        static const int8_t taps[CALIB_TAPS] = { 3, 3, 2, 4, 3, -12, 3, 3, 4, 2, 3, 3, 14, 3, 2, 4 };
        run(&c, taps, CALIB_TAPS, &r);
        CHECK_EQ(r.median, 3);
        CHECK_EQ(r.offset, 3);
        CHECK_EQ(r.spread, 0); /* sorted[4..11] are all 3 */
    }

    /* Even count: mean of the middle two, rounded away from zero. */
    {
        static const int8_t up[] = { 1, 2, 3, 4 };      /* 2.5 -> 3 */
        static const int8_t down[] = { -1, -2, -3, -4 }; /* -2.5 -> -3 */
        static const int8_t odd[] = { 5, -1, 2 };        /* odd count: the middle one */
        run(&c, up, 4, &r);
        CHECK_EQ(r.median, 3);
        run(&c, down, 4, &r);
        CHECK_EQ(r.median, -3);
        run(&c, odd, 3, &r);
        CHECK_EQ(r.median, 2);
    }

    /* Order does not matter; spread is the middle half (sorted[4] .. sorted[11]). */
    {
        static const int8_t taps[CALIB_TAPS] = { 7, -6, 5, -4, 3, -2, 1, 0, -1, 2, -3, 4, -5, 6, -7, 8 };
        run(&c, taps, CALIB_TAPS, &r);
        CHECK_EQ(r.median, 1); /* middle two are 0 and 1 -> 0.5 -> 1 */
        CHECK_EQ(r.spread, 7); /* -3 .. 4 */
    }

    /* The offset is clamped to the tuning range; the median is reported unclamped. */
    {
        int8_t late[CALIB_TAPS], early[CALIB_TAPS];
        for (i = 0; i < CALIB_TAPS; i++) {
            late[i] = 20;
            early[i] = -18;
        }
        run(&c, late, CALIB_TAPS, &r);
        CHECK_EQ(r.median, 20);
        CHECK_EQ(r.offset, CALIB_OFFSET_MAX);
        run(&c, early, CALIB_TAPS, &r);
        CHECK_EQ(r.offset, CALIB_OFFSET_MIN);
    }

    /* calib_add reports completion on the last tap and ignores extras; no taps -> zeros. */
    calib_reset(&c);
    for (i = 0; i + 1 < CALIB_TAPS; i++)
        CHECK_EQ(calib_add(&c, 1), 0);
    CHECK_EQ(calib_add(&c, 1), 1);
    CHECK_EQ(calib_add(&c, 9), 1);
    CHECK_EQ(c.count, CALIB_TAPS);
    calib_result(&c, &r);
    CHECK_EQ(r.median, 1);
    calib_reset(&c);
    calib_result(&c, &r);
    CHECK_EQ(r.median, 0);
    CHECK_EQ(r.spread, 0);
}
