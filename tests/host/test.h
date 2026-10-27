#ifndef TEST_H
#define TEST_H

/* Minimal host test harness: each test is a void(void) function registered in run_tests.c. */

#include <stdio.h>

extern int test_failures;

#define CHECK_EQ(actual, expected)                                                   \
    do {                                                                             \
        long a_ = (long)(actual), e_ = (long)(expected);                             \
        if (a_ != e_) {                                                              \
            fprintf(stderr, "%s:%d: %s == %ld, expected %ld\n", __FILE__, __LINE__, \
                    #actual, a_, e_);                                                \
            test_failures++;                                                         \
        }                                                                            \
    } while (0)

#endif
