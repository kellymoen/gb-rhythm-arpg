#ifndef GB_SETTINGS_H
#define GB_SETTINGS_H

#include <stdint.h>
#include <gbdk/platform.h>

/* Player settings in battery SRAM (MBC5, SRAM bank 0). One small versioned record at 0xA000:
 *   +0  magic "BARP"      +4  version (SETTINGS_VERSION)
 *   +5  latency offset (int8, frames)
 *   +6  check = ~(sum of bytes +0..+5)
 * Bytes from +7 are unused. A new field bumps the version; a record with another version, a bad
 * magic or checksum, or an out-of-range value is ignored and the tuning defaults stay. */

#define SETTINGS_VERSION 1

typedef struct {
    int8_t latency_offset; /* tuning timing.latency_offset, [-15..15] */
} settings_t;

/* Read the saved record. Returns 1 and fills `out` if it is valid, else 0. */
uint8_t settings_read(settings_t *out) BANKED;

/* Write the record. Returns 1 if it reads back intact. */
uint8_t settings_write(const settings_t *s) BANKED;

/* Boot, after tuning_reset(): apply a valid saved record over the tuning defaults. */
void settings_load(void) BANKED;

#endif
