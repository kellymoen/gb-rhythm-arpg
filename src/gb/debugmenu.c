#ifdef DEBUG

#pragma bank 255

#include <gb/gb.h>
#include <gbdk/emu_debug.h>

#include "core/beat.h"
#include "gb/debugmenu.h"
#include "gb/text.h"
#include "tuning.h"

#define WIDTH 20
#define PAGE_ROWS (DEBUGMENU_ROWS - 1) /* params per page, under the title row */
#define ALL_ROWS ((1 << DEBUGMENU_ROWS) - 1)
#define COL_LABEL 1
#define COL_VALUE_END 19 /* values are right-aligned in columns 13-18 */
#define COL_PAGE 15      /* "n/m" */

typedef struct {
    const char *label; /* TUNING_LABEL_MAX columns max */
    const char *toml;  /* "table.key" as in data/tuning.toml */
    int16_t *value;
    int16_t min;
    int16_t max;
} param_t;

typedef struct {
    const char *title; /* the [table] */
    uint8_t first;     /* index into params */
    uint8_t count;
} table_t;

#define PARAM_ROW(field, label, toml, lo, hi) { label, toml, &tuning.field, lo, hi },
static const param_t params[TUNING_PARAM_COUNT] = { TUNING_PARAM_LIST(PARAM_ROW) };

#define TABLE_ROW(title, first, count) { title, first, count },
static const table_t tables[TUNING_TABLE_COUNT] = { TUNING_TABLE_LIST(TABLE_ROW) };

static uint8_t table;  /* current page: tables[table], params from its `offset`-th on */
static uint8_t offset; /* a multiple of PAGE_ROWS */
static uint8_t cursor; /* param row on the page, 0..page_count()-1 */
static uint8_t dirty;  /* bit per menu row still to draw */
static char line[WIDTH + 1];

static uint8_t page_count(void)
{
    uint8_t left = tables[table].count - offset;

    return left < PAGE_ROWS ? left : PAGE_ROWS;
}

static void put(uint8_t col, const char *s)
{
    while (*s && col < WIDTH)
        line[col++] = *s++;
}

/* Digits by repeated subtraction (no 16-bit divide), right-aligned to end before column `end`. */
static const uint16_t powers[] = { 10000, 1000, 100, 10, 1 };

static void put_int(uint8_t end, int16_t v, uint8_t sign)
{
    char digits[5];
    uint8_t n = 0, i, d;
    uint16_t u = v < 0 ? (uint16_t)-v : (uint16_t)v;

    for (i = 0; i < 5; i++) {
        for (d = 0; u >= powers[i]; d++)
            u -= powers[i];
        if (d || n || i == 4)
            digits[n++] = '0' + d;
    }
    while (n)
        line[--end] = digits[--n];
    if (v < 0)
        line[--end] = '-';
    else if (sign)
        line[--end] = '+';
}

/* The whole row in one text_print: one text job, and no separate clear. */
static void draw_row(uint8_t row, uint8_t top)
{
    const param_t *p;
    uint8_t i, n, pages;

    for (i = 0; i < WIDTH; i++)
        line[i] = ' ';
    line[WIDTH] = 0;
    if (row == 0) {
        put(COL_LABEL, tables[table].title);
        if (tables[table].count > PAGE_ROWS) {
            for (n = 1, i = PAGE_ROWS; i < offset + PAGE_ROWS; i += PAGE_ROWS)
                n++;
            for (pages = 1, i = PAGE_ROWS; i < tables[table].count; i += PAGE_ROWS)
                pages++;
            line[COL_PAGE] = '0' + n;
            line[COL_PAGE + 1] = '/';
            line[COL_PAGE + 2] = '0' + pages;
        }
    } else if (row - 1 < page_count()) {
        p = &params[tables[table].first + offset + row - 1];
        if (row - 1 == cursor)
            line[0] = '>';
        put(COL_LABEL, p->label);
        put_int(COL_VALUE_END, *p->value, p->min < 0);
    }
    text_print(0, top + row, line);
}

static void change(const param_t *p, int8_t dir)
{
    int16_t v = *p->value + dir;

    /* step slots must divide the beat evenly */
    if (p->value == &tuning.timing_steps_per_beat)
        while (v >= p->min && v <= p->max && BEAT_TICKS % v)
            v += dir;
    if (v >= p->min && v <= p->max)
        *p->value = v;
}

static void turn_page(uint8_t forward)
{
    uint8_t count;

    if (forward) {
        offset += PAGE_ROWS;
        if (offset >= tables[table].count) {
            offset = 0;
            table = table + 1 < TUNING_TABLE_COUNT ? table + 1 : 0;
        }
    } else if (offset) {
        offset -= PAGE_ROWS;
    } else {
        table = table ? table - 1 : TUNING_TABLE_COUNT - 1;
        for (count = tables[table].count; offset + PAGE_ROWS < count; offset += PAGE_ROWS)
            ;
    }
    if (cursor >= page_count())
        cursor = page_count() - 1;
    dirty = ALL_ROWS;
}

static void dump(void)
{
    uint8_t i;

    EMU_printf("# tuning values (paste into data/tuning.toml)");
    for (i = 0; i < TUNING_PARAM_COUNT; i++)
        EMU_printf("%s = %d", params[i].toml, *params[i].value);
}

void debugmenu_draw(uint8_t top) BANKED
{
    (void)top;
    dirty = ALL_ROWS;
}

uint8_t debugmenu_update(uint8_t edges, uint8_t top) BANKED
{
    uint8_t row, old = cursor;

    if (edges & J_UP)
        cursor = cursor ? cursor - 1 : page_count() - 1;
    else if (edges & J_DOWN)
        cursor = cursor + 1 < page_count() ? cursor + 1 : 0;
    else if (edges & (J_LEFT | J_RIGHT))
        change(&params[tables[table].first + offset + cursor], edges & J_LEFT ? -1 : 1);
    else if (edges & J_A)
        turn_page(1);
    else if (edges & J_B)
        turn_page(0);
    else if (edges & J_START)
        dump();
    if (edges & (J_UP | J_DOWN | J_LEFT | J_RIGHT))
        dirty |= (1 << (old + 1)) | (1 << (cursor + 1));

    if (!dirty)
        return 0;
    for (row = 0; !(dirty & (1 << row)); row++)
        ;
    dirty &= ~(1 << row);
    draw_row(row, top);
    return 1;
}

#else
typedef int debugmenu_disabled_t; /* release builds: keep the translation unit non-empty */
#endif
