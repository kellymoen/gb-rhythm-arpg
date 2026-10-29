#ifndef GB_VRAM_STREAM_H
#define GB_VRAM_STREAM_H

#include <gb/gb.h>
#include <stdint.h>

/* Streams character frames' tiles from ROM to VRAM while the LCD is on (ADR 0001: the CPU copies,
 * no HDMA). Each job owns a destination slot that is NOT on screen: the owner shows the slot only
 * after its job reports VJ_READY, so a half-copied frame is never displayed (gb/spriteanim.c keeps
 * two slots per character and swaps them).
 *
 * The copy waits for each HBlank (mode 0) and writes a few bytes in it, with interrupts off for at
 * most one scanline at a time, so it is safe anywhere in the frame and never touches VRAM in mode 3.
 * It costs about one scanline per 4-6 bytes (a 12-tile frame, 192 bytes, takes ~38-46 lines), so the
 * main loop streams in the time it has left: vram_stream_update(deadline) copies until LY reaches
 * the deadline and a job that does not finish carries on in the next call, still hidden. Jobs are
 * served in the order they were added (priority). */

#define VJ_IDLE 0
#define VJ_COPYING 1
#define VJ_READY 2

typedef struct {
    const uint8_t *src; /* next byte to copy, in ROM bank `bank` */
    uint8_t *dst;       /* next VRAM byte */
    uint8_t bank;
    uint8_t units;      /* 2-byte units left */
    uint8_t state;      /* VJ_* */
} vram_job_t;

#define VRAM_STREAM_JOBS 6

/* Scene start: forget every job. */
void vram_stream_reset(void) BANKED;

/* Register a job (once, at scene start). Earlier jobs are served first. */
void vram_stream_add(vram_job_t *j) BANKED;

/* Ask for `tiles` 8x8 tiles from `src` (ROM bank `bank`) to be copied to VRAM tile `tile` (0x8000
 * area). Restarts the job if it was still copying. */
void vram_stream_submit(vram_job_t *j, uint8_t bank, const uint8_t *src, uint8_t tile, uint8_t tiles) NONBANKED;

/* Main loop, once per frame, last: copy pending jobs until the scanline `deadline_ly` (< 144) starts.
 * A finished job becomes VJ_READY; its owner shows it and sets it back to VJ_IDLE. Returns how many
 * jobs became ready. With the LCD off it copies everything. */
uint8_t vram_stream_update(uint8_t deadline_ly) BANKED;
extern uint8_t vram_stream_last_bytes; /* bytes copied by the last call, for tests and measurements */

/* VBlank streaming (on: from scene start; off: before leaving the scene). An LCD interrupt at line
 * 143 copies ~8-9 tiles of the job vram_stream_update() left unfinished, during VBlank, without
 * waiting for HBlanks; the VBlank ISR then runs ~7 lines later. vram_stream_update() still copies in
 * the main loop's spare time first. */
void vram_stream_vblank(uint8_t on) BANKED;
extern uint8_t vram_stream_vblank_bytes; /* bytes copied by the last handler run */

/* Copy now, however long it takes, waiting for HBlanks as needed (safe with the LCD on). */
void vram_copy_tiles(uint8_t tile, uint8_t bank, const uint8_t *src, uint8_t tiles) BANKED;

#endif
