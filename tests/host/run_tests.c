#include "test.h"

int test_failures = 0;

void test_iso_project(void);
void test_iso_depth(void);
void test_tuning_defaults(void);

static void (*const tests[])(void) = {
    test_iso_project,
    test_iso_depth,
    test_tuning_defaults,
};

int main(void)
{
    unsigned i, n = sizeof tests / sizeof tests[0];
    for (i = 0; i < n; i++)
        tests[i]();
    if (test_failures) {
        fprintf(stderr, "%d check(s) failed\n", test_failures);
        return 1;
    }
    printf("%u host tests passed\n", n);
    return 0;
}
