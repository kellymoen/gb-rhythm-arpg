#include "test.h"
#include "core/iso.h"

#define PX(n) ((int16_t)((n) * (1 << ISO_SUBPX_SHIFT)))

void test_iso_project(void)
{
    iso_screen_t s;

    iso_project(0, 0, &s);
    CHECK_EQ(s.x, 0);
    CHECK_EQ(s.y, 0);

    /* One 32x16 diamond step along +wx: right 16, down 8. */
    iso_project(PX(16), 0, &s);
    CHECK_EQ(s.x, 16);
    CHECK_EQ(s.y, 8);

    /* Along +wy: left 16, down 8. */
    iso_project(0, PX(16), &s);
    CHECK_EQ(s.x, -16);
    CHECK_EQ(s.y, 8);

    /* Screen-up (D-pad Up) is the -wx,-wy diagonal. */
    iso_project(PX(-10), PX(-10), &s);
    CHECK_EQ(s.x, 0);
    CHECK_EQ(s.y, -10);

    /* Arena corner: 256 px along both axes stays in range. */
    iso_project(PX(256), PX(256), &s);
    CHECK_EQ(s.x, 0);
    CHECK_EQ(s.y, 256);
}

void test_iso_depth(void)
{
    CHECK_EQ(iso_depth(PX(4), PX(4)) > iso_depth(PX(2), PX(4)), 1);
    CHECK_EQ(iso_depth(PX(1), PX(3)), iso_depth(PX(3), PX(1)));
}
