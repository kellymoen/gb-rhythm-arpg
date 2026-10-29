#pragma bank 255

#include <gb/gb.h>

#include "gb/vram_stream.h"

#include <stddef.h>

typedef char vram_job_layout_check[(offsetof(vram_job_t, src) == 0 && offsetof(vram_job_t, dst) == 2 &&
                                    offsetof(vram_job_t, bank) == 4 && offsetof(vram_job_t, units) == 5 &&
                                    offsetof(vram_job_t, state) == 6) ? 1 : -1];

/* Banked, except the copy itself, which maps the tile data's bank and so lives in bank 0. */

static vram_job_t *jobs[VRAM_STREAM_JOBS];
static uint8_t job_count;
uint8_t vram_stream_last_bytes;

/* vs_copy() arguments and results (globals keep the asm free of calling-convention details). */
static const uint8_t *vs_src;
static uint8_t *vs_dst;
static uint8_t vs_units;    /* in: units to copy; out: units not copied (deadline) */
static uint8_t vs_deadline; /* stop before a scanline >= this starts (255: never) */

/* Copy vs_units 2-byte units from vs_src to VRAM at vs_dst; leaves both pointers past the copy.
 *
 * LCD on: per scanline, wait for mode 3, then for its end (mode 0), then write 4 bytes; while STAT
 * still reads mode 0, write 2 more at a time. Timing in M-cycles, T = mode 3 -> 0 transition: the
 * wait loop sees mode 0 by T+7 and the 4th write lands by T+36. VRAM locks again when the next line's
 * mode 3 starts, at least 87 dots (HBlank, with 10 OBJs on the line) + 80 dots (mode 2) = 41.75
 * M-cycles after T. Each extra pair starts from a STAT read that saw mode 0 and writes within 14
 * M-cycles, inside the 20-cycle mode 2 that must still follow. In VBlank (LY 144-152) it writes
 * without waiting. Interrupts are off from the wait to the last write of the line (at most about one
 * scanline), so an ISR can never split a wait from its writes. Before each scanline it stops if
 * LY >= vs_deadline, leaving the rest in vs_units.
 *
 * LCD off: plain copy of everything. */
static void vs_copy(void) NONBANKED __naked
{
    __asm
        ld      hl, #_vs_dst
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      hl, #_vs_units
        ld      b, (hl)
        ld      hl, #_vs_src
        ld      a, (hl+)
        ld      h, (hl)
        ld      l, a
        inc     b
        dec     b
        jr      z, 9$
        ldh     a, (0x40)               ; LCDC
        bit     7, a
        jr      z, 8$
1$:
        ld      a, (_vs_deadline)
        ld      c, a
        ldh     a, (0x44)               ; LY
        cp      a, c
        jr      nc, 9$                  ; past the deadline: stop
        ld      c, #0x41                ; STAT, for ldh a,(c)
        di
2$:                                     ; wait for mode 3, or VBlank
        ldh     a, (0x44)               ; LY
        cp      #144
        jr      nc, 6$
        ldh     a, (c)
        and     #3
        cp      #3
        jr      nz, 2$
3$:                                     ; wait for mode 3 to end
        ldh     a, (c)
        and     #3
        jr      nz, 3$
4$:                                     ; 4 bytes: safe in any HBlank
        ld      a, (hl+)
        ld      (de), a
        inc     de
        ld      a, (hl+)
        ld      (de), a
        inc     de
        dec     b
        jr      z, 7$
        ld      a, (hl+)
        ld      (de), a
        inc     de
        ld      a, (hl+)
        ld      (de), a
        inc     de
        dec     b
        jr      z, 7$
5$:                                     ; 2 more while STAT still reads mode 0
        ldh     a, (c)
        and     #3
        jr      nz, 10$
        ld      a, (hl+)
        ld      (de), a
        inc     de
        ld      a, (hl+)
        ld      (de), a
        inc     de
        dec     b
        jr      nz, 5$
7$:
        ei
        jr      9$
10$:
        ei                              ; let a pending interrupt in between scanlines
        jr      1$
6$:                                     ; VBlank: lines 144-152 still have a full line left
        cp      #153
        jr      nc, 2$
        jr      4$
8$:                                     ; LCD off
        ld      a, (hl+)
        ld      (de), a
        inc     de
        ld      a, (hl+)
        ld      (de), a
        inc     de
        dec     b
        jr      nz, 8$
9$:
        ld      a, b
        ld      (_vs_units), a
        ld      a, l
        ld      (_vs_src), a
        ld      a, h
        ld      (_vs_src + 1), a
        ld      a, e
        ld      (_vs_dst), a
        ld      a, d
        ld      (_vs_dst + 1), a
        ret
    __endasm;
}

/* VBlank streaming. An LCD (LYC = 143) interrupt starts at the last visible line, waits for its
 * HBlank, finishes a tile the HBlank copy left half done (2-byte units), then copies whole tiles of
 * the first pending job without waiting (~93 M-cycles a tile)
 * until LY 148, so the VBlank ISR that follows (from LY ~150) finishes the OAM DMA before line 0. The
 * VBlank ISR (music, input) runs that much later; nothing in it depends on its scanline. */
#define VB_LYC 143
#define VB_LAST_LY 148 /* no tile starts at or after this line */

static vram_job_t *vb_job;  /* the job the handler copies (written with interrupts off) */
static const uint8_t *vb_src;
static uint8_t vb_left;
static uint8_t vb_on;
uint8_t vram_stream_vblank_bytes; /* copied by the last handler run, for tests and measurements */

/* The LCD interrupt handler (GBDK's dispatcher saves AF, BC, DE, HL). vram_job_t is read by byte
 * offset: src 0, dst 2, bank 4, units 5, state 6. */
static void vb_handler(void) NONBANKED __naked
{
    __asm
        xor     a, a
        ld      (_vram_stream_vblank_bytes), a
        ld      hl, #_vb_job
        ld      a, (hl+)
        ld      h, (hl)
        ld      l, a
        or      a, h
        ret     z                       ; no job
        push    hl
        ld      de, #6
        add     hl, de
        ld      a, (hl)
        pop     hl
        cp      a, #VJ_COPYING
        ret     nz
        push    hl                      ; the job, for the write-back
        ld      a, (hl+)                ; src
        ld      (_vb_src), a
        ld      a, (hl+)
        ld      (_vb_src + 1), a
        ld      e, (hl)                 ; dst
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      a, (__current_bank)
        ld      c, a                    ; the interrupted code's bank
        ld      a, (hl+)                ; the job's bank
        ld      (__current_bank), a
        ld      (0x2000), a
        ld      a, (hl)                 ; units
        ld      (_vb_left), a
        ld      b, a
        ld      hl, #_vb_src
        ld      a, (hl+)
        ld      h, (hl)
        ld      l, a
1$:                                     ; line 143 is drawn once its HBlank starts
        ldh     a, (0x41)
        and     a, #2
        jr      nz, 1$
        ld      a, b                    ; the HBlank copy may have stopped inside a tile:
        and     a, #7                   ; finish that tile first (the tile loop below needs
        jr      z, 2$                   ; whole, aligned tiles, or units wraps and it runs away)
        ldh     a, (0x44)               ; LY
        cp      a, #VB_LYC
        jr      c, 3$                   ; wrapped to a new frame: stop
        cp      a, #VB_LAST_LY
        jr      nc, 3$
5$:
        ld      a, (hl+)
        ld      (de), a
        inc     de
        ld      a, (hl+)
        ld      (de), a
        inc     de
        dec     b
        ld      a, b
        and     a, #7
        jr      nz, 5$
2$:
        ld      a, b
        or      a, a
        jr      z, 3$
        ldh     a, (0x44)               ; LY
        cp      a, #VB_LYC
        jr      c, 3$                   ; wrapped to a new frame: stop
        cp      a, #VB_LAST_LY
        jr      nc, 3$
        .rept   15                      ; tiles are 16-byte aligned: no carry into D inside one
        ld      a, (hl+)
        ld      (de), a
        inc     e
        .endm
        ld      a, (hl+)
        ld      (de), a
        inc     de
        ld      a, b
        sub     a, #8
        ld      b, a
        jr      2$
3$:
        ld      a, c                    ; restore the bank
        ld      (__current_bank), a
        ld      (0x2000), a
        ld      a, l
        ld      (_vb_src), a
        ld      a, h
        ld      (_vb_src + 1), a
        pop     hl                      ; the job
        ld      a, (_vb_src)
        ld      (hl+), a
        ld      a, (_vb_src + 1)
        ld      (hl+), a
        ld      a, e
        ld      (hl+), a
        ld      a, d
        ld      (hl+), a
        inc     hl                      ; bank
        ld      a, b
        ld      (hl+), a                ; units
        or      a, a
        jr      nz, 4$
        ld      (hl), #VJ_READY
4$:
        ld      a, (_vb_left)           ; bytes = 2 * (units before - units after)
        sub     a, b
        add     a, a
        ld      (_vram_stream_vblank_bytes), a
        ret
    __endasm;
}

void vram_stream_vblank(uint8_t on) BANKED
{
    if (on == vb_on)
        return;
    CRITICAL {
        vb_job = 0;
        if (on) {
            add_LCD(vb_handler);
            LYC_REG = VB_LYC;
            STAT_REG |= STATF_LYC;
            set_interrupts(IE_REG | LCD_IFLAG);
        } else {
            set_interrupts(IE_REG & ~LCD_IFLAG);
            STAT_REG &= ~STATF_LYC;
            remove_LCD(vb_handler);
        }
    }
    vb_on = on;
}

/* Copy what the deadline allows of job j (its ROM bank mapped meanwhile). Returns units copied. */
static uint8_t copy_job(vram_job_t *j) NONBANKED
{
    uint8_t saved = CURRENT_BANK, left = j->units;

    SWITCH_ROM(j->bank);
    vs_src = j->src;
    vs_dst = j->dst;
    vs_units = left;
    vs_copy();
    j->src = vs_src;
    j->dst = vs_dst;
    j->units = vs_units;
    SWITCH_ROM(saved);
    return left - vs_units;
}

void vram_stream_reset(void) BANKED
{
    job_count = 0;
}

void vram_stream_add(vram_job_t *j) BANKED
{
    j->state = VJ_IDLE;
    j->units = 0;
    if (job_count < VRAM_STREAM_JOBS)
        jobs[job_count++] = j;
}

void vram_stream_submit(vram_job_t *j, uint8_t bank, const uint8_t *src, uint8_t tile, uint8_t tiles) NONBANKED
{
    j->state = VJ_IDLE; /* first, so nothing copies a half-written job */
    j->bank = bank;
    j->src = src;
    j->dst = (uint8_t *)0x8000 + ((uint16_t)tile << 4);
    j->units = tiles << 3; /* 16 bytes = 8 units per tile; tiles <= 31 */
    j->state = j->units ? VJ_COPYING : VJ_READY;
}

uint8_t vram_stream_update(uint8_t deadline_ly) BANKED
{
    uint8_t i, ready = 0, units = 0;
    vram_job_t *j, *next = 0;

    vs_deadline = deadline_ly;
    for (i = 0; i < job_count; i++) {
        j = jobs[i];
        if (j->state == VJ_READY)
            ready++; /* finished by the VBlank handler */
        if (j->state != VJ_COPYING)
            continue;
        if (!next) {
            units += copy_job(j);
            if (!j->units) {
                j->state = VJ_READY;
                ready++;
                continue;
            }
            next = j; /* out of time: the VBlank handler goes on with it */
        }
    }
    if (vb_on) {
        CRITICAL {
            vb_job = next;
        }
    }
    vram_stream_last_bytes = units << 1;
    return ready;
}

void vram_copy_tiles(uint8_t tile, uint8_t bank, const uint8_t *src, uint8_t tiles) BANKED
{
    vram_job_t j;

    vram_stream_submit(&j, bank, src, tile, tiles);
    vs_deadline = 0xFF;
    copy_job(&j);
}
