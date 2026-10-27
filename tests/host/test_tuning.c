#include "test.h"
#include "tuning.h"

void test_tuning_defaults(void)
{
    tuning.timing_perfect_window = 99;
    tuning_reset();
    CHECK_EQ(tuning.timing_perfect_window, tuning_defaults.timing_perfect_window);
    CHECK_EQ(tuning.timing_perfect_window < tuning.timing_good_window, 1);
}
