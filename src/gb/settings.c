#pragma bank 255

#include <gb/gb.h>

#include "core/calib.h"
#include "gb/settings.h"
#include "tuning.h"

#define RECORD_SIZE 7
#define CHECK_AT (RECORD_SIZE - 1)

static const uint8_t magic[4] = { 'B', 'A', 'R', 'P' };

static uint8_t check(const uint8_t *b)
{
    uint8_t i, sum = 0;

    for (i = 0; i < CHECK_AT; i++)
        sum += b[i];
    return (uint8_t)~sum;
}

static void sram_read(uint8_t *b)
{
    uint8_t i;

    ENABLE_RAM;
    SWITCH_RAM(0);
    for (i = 0; i < RECORD_SIZE; i++)
        b[i] = _SRAM[i];
    DISABLE_RAM;
}

uint8_t settings_read(settings_t *out) BANKED
{
    uint8_t b[RECORD_SIZE], i;
    int8_t latency;

    sram_read(b);
    for (i = 0; i < 4; i++)
        if (b[i] != magic[i])
            return 0;
    if (b[4] != SETTINGS_VERSION || b[CHECK_AT] != check(b))
        return 0;
    latency = (int8_t)b[5];
    if (latency < CALIB_OFFSET_MIN || latency > CALIB_OFFSET_MAX)
        return 0;
    out->latency_offset = latency;
    return 1;
}

uint8_t settings_write(const settings_t *s) BANKED
{
    uint8_t b[RECORD_SIZE], back[RECORD_SIZE], i;

    for (i = 0; i < 4; i++)
        b[i] = magic[i];
    b[4] = SETTINGS_VERSION;
    b[5] = (uint8_t)s->latency_offset;
    b[CHECK_AT] = check(b);

    ENABLE_RAM;
    SWITCH_RAM(0);
    for (i = 0; i < RECORD_SIZE; i++)
        _SRAM[i] = b[i];
    DISABLE_RAM;

    sram_read(back);
    for (i = 0; i < RECORD_SIZE; i++)
        if (back[i] != b[i])
            return 0;
    return 1;
}

void settings_load(void) BANKED
{
    settings_t s;

    if (settings_read(&s))
        tuning.timing_latency_offset = s.latency_offset;
}
