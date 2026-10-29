#pragma bank 255

#include <gb/gb.h>
#include <stddef.h>

#include "core/budgets.h"
#include "gb/oam.h"
#include "gb/video.h"

/* Per-frame paths are written for SDCC: global arrays instead of pointer chains, and the OAM write
 * itself in assembly. */

/* emit_all() reads oam_draw_t by byte offset; keep these in step with the struct. */
typedef char oam_draw_layout_check[(offsetof(oam_draw_t, look) == 4 &&
                                    offsetof(oam_look_t, count) == 2 &&
                                    offsetof(oam_look_t, tile) == 3 &&
                                    offsetof(oam_look_t, flip) == 4 &&
                                    OAM_WORLD * 4 == 64 && OAM_WORLD_COUNT == 24) ? 1 : -1];

/* Pivot range, in OAM coordinates (screen + 16, + 8), where every part of any art within the canvas
 * budget is on screen: dy is -(H-1) .. H-16 and the (mirrored) x offset -W .. W-8. */
#define FAST_YLO BUDGET_PLAYER_H
#define FAST_YHI (DEVICE_SCREEN_PX_HEIGHT + 15 - (BUDGET_PLAYER_H - 16))
#define FAST_XLO (BUDGET_PLAYER_W + 1)
#define FAST_XHI (DEVICE_SCREEN_PX_WIDTH + 7 - (BUDGET_PLAYER_W - 8))

static const oam_draw_t *draws[OAM_MAX_DRAWS]; /* sorted nearest first by oam_add */
static int16_t keys[OAM_MAX_DRAWS];
static uint8_t draw_count, rows_total, parts_total, rotate;
uint8_t oam_overflow_frames;

/* emit_all() state */
static uint8_t em_first, em_k, em_todo, em_n, em_tile, em_flip, em_end_last;
static int16_t em_y16, em_x16; /* pivot in OAM coordinates */

void oam_begin(void) NONBANKED
{
    draw_count = rows_total = parts_total = 0;
}

void oam_add(const oam_draw_t *d, int16_t k) NONBANKED
{
    uint8_t i = draw_count;

    if (i == OAM_MAX_DRAWS)
        return;
    rows_total += d->look.per_row;
    parts_total += d->look.count;
    /* insertion: nearest (largest depth) first; equal depths keep their add order */
    for (; i && keys[i - 1] < k; i--) {
        keys[i] = keys[i - 1];
        draws[i] = draws[i - 1];
    }
    keys[i] = k;
    draws[i] = d;
    draw_count++;
}

/* Could some scanline get more than BUDGET_OBJS_PER_LINE OBJs? The busiest line of overlapping
 * row ranges is one of their top lines, so test those. Only runs when the totals say it might. */
static uint8_t overflows(void)
{
    uint8_t i, j, per_line;
    int16_t top, t;

    for (i = 0; i < draw_count; i++) {
        top = draws[i]->y + draws[i]->look.top;
        per_line = 0;
        for (j = 0; j < draw_count; j++) {
            t = draws[j]->y;
            if (t + draws[j]->look.top <= top && top < t + draws[j]->look.bottom)
                per_line += draws[j]->look.per_row;
        }
        if (per_line > BUDGET_OBJS_PER_LINE)
            return 1;
    }
    return 0;
}

/* Write every draw, starting at draws[em_first] and wrapping, into shadow OAM 16..39, then hide the
 * entries used last frame and not this one. */
static void emit_all(void) __naked
{
    __asm
        ld      de, #(_shadow_OAM + 64)
        ld      a, (_draw_count)
        or      a, a
        jp      z, 90$
        ld      (_em_todo), a
        ld      a, (_em_first)
        ld      (_em_k), a
10$:                                    ; next draw: HL = draws[em_k], em_k = (em_k + 1) % count
        ld      a, (_em_k)
        ld      c, a
        inc     a
        ld      hl, #_draw_count
        cp      a, (hl)
        jr      c, 11$
        xor     a, a
11$:
        ld      (_em_k), a
        ld      a, c
        add     a, a
        add     a, #<(_draws)
        ld      l, a
        ld      a, #0
        adc     a, #>(_draws)
        ld      h, a
        ld      a, (hl+)
        ld      h, (hl)
        ld      l, a
        ld      a, (hl+)                ; em_x16 = x + 8
        add     a, #8
        ld      (_em_x16), a
        ld      a, (hl+)
        adc     a, #0
        ld      (_em_x16 + 1), a
        ld      a, (hl+)                ; em_y16 = y + 16
        add     a, #16
        ld      (_em_y16), a
        ld      a, (hl+)
        adc     a, #0
        ld      (_em_y16 + 1), a
        ld      a, (hl+)                ; parts -> BC
        ld      c, a
        ld      a, (hl+)
        ld      b, a
        ld      a, (hl+)                ; count
        or      a, a
        jp      z, 50$
        ld      (_em_n), a
        ld      a, (hl+)
        ld      (_em_tile), a
        ld      a, (hl)
        ld      (_em_flip), a
        ld      h, b
        ld      l, c                    ; HL = parts
        ld      a, (_em_y16 + 1)        ; pivot in the safe box?
        or      a, a
        jr      nz, 40$
        ld      a, (_em_x16 + 1)
        or      a, a
        jr      nz, 40$
        ld      a, (_em_y16)
        cp      a, #FAST_YLO
        jr      c, 40$
        cp      a, #(FAST_YHI + 1)
        jr      nc, 40$
        ld      b, a
        ld      a, (_em_x16)
        cp      a, #FAST_XLO
        jr      c, 40$
        cp      a, #(FAST_XHI + 1)
        jr      nc, 40$
        ld      c, a
        ld      a, (_em_n)              ; room for every part? e + 4n <= 160
        add     a, a
        add     a, a
        add     a, e
        cp      a, #161
        jr      nc, 40$
        ld      a, (_em_flip)
        or      a, a
        jr      nz, 30$
20$:                                    ; fast, as drawn: y + dy, x + dx
        ld      a, (hl+)
        add     a, b
        ld      (de), a
        inc     e                       ; shadow_OAM is 256-byte aligned
        ld      a, (hl+)
        add     a, c
        ld      (de), a
        inc     e
        ld      a, (_em_tile)
        add     a, (hl)
        inc     hl
        ld      (de), a
        inc     e
        ld      a, (hl+)
        ld      (de), a
        inc     e
        ld      a, (_em_n)
        dec     a
        ld      (_em_n), a
        jr      nz, 20$
        jr      50$
30$:                                    ; fast, mirrored: x - 8 - dx, props ^ S_FLIPX
        ld      a, c
        sub     a, #8
        ld      c, a
31$:
        ld      a, (hl+)
        add     a, b
        ld      (de), a
        inc     e
        ld      a, c
        sub     a, (hl)
        inc     hl
        ld      (de), a
        inc     e
        ld      a, (_em_tile)
        add     a, (hl)
        inc     hl
        ld      (de), a
        inc     e
        ld      a, (_em_flip)
        xor     a, (hl)
        inc     hl
        ld      (de), a
        inc     e
        ld      a, (_em_n)
        dec     a
        ld      (_em_n), a
        jr      nz, 31$
        jr      50$
40$:                                    ; clipped: part by part
        ld      a, e
        cp      a, #160                 ; world OAM full
        jr      nc, 50$
        ld      a, (hl+)                ; dy
        call    80$
        jr      c, 45$
        ld      a, c
        ld      (de), a                 ; y (kept only if x is on screen too)
        ld      a, (_em_flip)
        or      a, a
        ld      a, (hl+)                ; dx
        jr      z, 41$
        cpl                             ; mirrored: -dx - 8
        sub     a, #7
41$:
        call    81$
        jr      c, 46$
        inc     e
        ld      a, c
        ld      (de), a
        inc     e
        ld      a, (_em_tile)
        add     a, (hl)
        inc     hl
        ld      (de), a
        inc     e
        ld      a, (_em_flip)
        xor     a, (hl)
        inc     hl
        ld      (de), a
        inc     e
        jr      47$
45$:
        inc     hl
46$:
        inc     hl
        inc     hl
47$:
        ld      a, (_em_n)
        dec     a
        ld      (_em_n), a
        jr      nz, 40$
50$:                                    ; draw done
        ld      a, (_em_todo)
        dec     a
        ld      (_em_todo), a
        jp      nz, 10$
90$:                                    ; hide what was used last frame and not now
        ld      a, (_em_end_last)
        ld      b, a
        ld      a, e
        ld      (_em_end_last), a
91$:
        ld      a, e
        cp      a, b
        ret     nc
        xor     a, a
        ld      (de), a
        inc     e
        inc     e
        inc     e
        inc     e
        jr      91$

80$:                                    ; C = em_y16 + (int8)A; carry if not 1..159
        push    hl
        ld      hl, #_em_y16
        ld      c, #160
        jr      82$
81$:                                    ; C = em_x16 + (int8)A; carry if not 1..167
        push    hl
        ld      hl, #_em_x16
        ld      c, #168
82$:
        push    bc                      ; limit
        ld      c, a
        rlca
        sbc     a, a                    ; sign extension
        ld      b, a
        ld      a, (hl+)
        add     a, c
        ld      c, a
        ld      a, (hl)
        adc     a, b
        pop     hl                      ; L = limit
        jr      nz, 88$                 ; high byte not 0: off screen
        ld      a, c
        or      a, a
        jr      z, 88$                  ; 0 hides
        cp      a, l                    ; carry if < limit (on screen)
        ccf
        pop     hl
        ret
88$:
        scf
        pop     hl
        ret
    __endasm;
}

void oam_end(void) BANKED
{
    em_first = 0;
    if (draw_count > 1 &&
        (parts_total > OAM_WORLD_COUNT || (rows_total > BUDGET_OBJS_PER_LINE && overflows()))) {
        oam_overflow_frames++;
        if (++rotate >= draw_count)
            rotate = 0;
        em_first = rotate;
    }
    emit_all();
}
