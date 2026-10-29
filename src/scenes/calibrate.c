#pragma bank 255

#include <gb/gb.h>
#include <string.h>

#include "audio/music.h"
#include "core/calib.h"
#include "gb/input.h"
#include "gb/overlay.h"
#include "gb/settings.h"
#include "gb/text.h"
#include "music.h"
#include "scenes/scene.h"
#include "tuning.h"

/* Calibration (CONTEXT.md, ADR 0008): the player taps A on each beat of a steady song; the median
 * raw error of CALIB_TAPS taps becomes the latency offset, saved to battery SRAM on Accept.
 *
 * While this scene runs, grading is switched to raw beats: latency offset 0 and one step slot per
 * beat, so a press's judgement.frames is its raw distance to the nearest beat. Musical hits are
 * off so a tap makes no sound of its own. The tuning values come back when the scene ends. */

/* The steady beat the player taps to (PROVISIONAL: the rhythm-test loop, whose kick and snare mark
 * every beat). A dedicated click song swaps in here. */
#define CALIB_SONG song_rhythmtest
#define PLAY_SONG(song) music_play(BANK(song), &song) /* expands CALIB_SONG before BANK() pastes */

#define ROW_TITLE 0
#define ROW_HELP 2
#define ROW_TAPS 5
#define ROW_GRID 7   /* 4 rows of 4 tap errors */
#define ROW_MEDIAN 12
#define ROW_SPREAD 13
#define ROW_CURRENT 14
#define ROW_PROMPT 16
#define ROW_BACK 17
#define LINE_W 19        /* lines start in column 1 */
#define VALUE_COL 8      /* where values start on the result lines */
#define PROMPT_DELAY 32  /* frames after the last tap before A/B act: a stray extra tap can't accept */
#define OVERLAY_X 104    /* DEBUG timing overlay, right of the tap counter */
#define OVERLAY_Y 40

enum { TAPPING, RESULT, SAVED };

/* Text jobs run one per frame, in this order (VRAM writes with the LCD on are slow). Grid cells
 * (drawn < calib.count) run after the grid clears and before the rest. */
#define JOB_CLEAR_GRID 0x000F /* one bit per grid row */
#define JOB_TAPS 0x0010
#define JOB_MEDIAN 0x0020
#define JOB_SPREAD 0x0040
#define JOB_CURRENT 0x0080
#define JOB_PROMPT 0x0100

static calib_t calib;
static calib_result_t result;
static uint8_t state, drawn, wait, save_ok;
static uint16_t jobs;
static int8_t latency; /* the offset in effect outside this scene */
static int16_t saved_steps, saved_hits;
static char line[LINE_W + 1];

/* Signed number (|v| < 200) without division; positive values get a '+'. Returns its length. */
static uint8_t put_num(char *p, int8_t v, uint8_t sign)
{
    uint8_t n = 0, u, tens = 0;

    if (v < 0) {
        p[n++] = '-';
        u = (uint8_t)-v;
    } else {
        if (v && sign)
            p[n++] = '+';
        u = (uint8_t)v;
    }
    while (u >= 10) {
        u -= 10;
        tens++;
    }
    if (tens >= 10) {
        p[n++] = '1';
        tens -= 10;
        p[n++] = '0' + tens;
    } else if (tens) {
        p[n++] = '0' + tens;
    }
    p[n++] = '0' + u;
    return n;
}

/* Fill `line` with spaces and put `s` at its start. Every line is LINE_W wide, so drawing one
 * overwrites whatever was there without a separate clear. */
static uint8_t line_start(const char *s)
{
    uint8_t n = 0;

    memset(line, ' ', LINE_W);
    line[LINE_W] = 0;
    while (s[n]) {
        line[n] = s[n];
        n++;
    }
    return n;
}

static void line_value(uint8_t row, const char *label, int8_t v, uint8_t sign)
{
    uint8_t n = VALUE_COL;

    line_start(label);
    n += put_num(line + n, v, sign);
    line[n] = 'F';
    text_print(1, row, line);
}

static void draw_cell(uint8_t k)
{
    char cell[4], num[4];
    uint8_t n = put_num(num, calib.err[k], 1), i;

    cell[0] = cell[1] = cell[2] = ' ';
    cell[3] = 0;
    for (i = 0; i < n; i++)
        cell[3 - n + i] = num[i];
    text_print(1 + (k & 3) * 5, ROW_GRID + (k >> 2), cell);
}

static void draw_taps(void)
{
    uint8_t n = line_start("TAPS ");

    n += put_num(line + n, (int8_t)calib.count, 0);
    line[n++] = '/';
    put_num(line + n, CALIB_TAPS, 0);
    text_print(1, ROW_TAPS, line);
}

static void draw_prompt(void)
{
    if (state == TAPPING)
        line_start("");
    else if (state == RESULT)
        line_start("A: ACCEPT  B: RETRY");
    else if (save_ok)
        line_start("SAVED.     B: RETRY");
    else
        line_start("NOT SAVED! B: RETRY");
    text_print(1, ROW_PROMPT, line);
}

static void run_job(void)
{
    uint8_t i;

    for (i = 0; i < 4; i++)
        if (jobs & (1 << i)) {
            text_clear(0, ROW_GRID + i, 20);
            jobs &= ~(1 << i);
            return;
        }
    if (drawn < calib.count) {
        draw_cell(drawn++);
    } else if (jobs & JOB_TAPS) {
        draw_taps();
        jobs &= ~JOB_TAPS;
    } else if (jobs & JOB_MEDIAN) {
        if (state == TAPPING)
            text_clear(1, ROW_MEDIAN, LINE_W);
        else
            line_value(ROW_MEDIAN, "MEDIAN", result.median, 1);
        jobs &= ~JOB_MEDIAN;
    } else if (jobs & JOB_SPREAD) {
        if (state == TAPPING)
            text_clear(1, ROW_SPREAD, LINE_W);
        else
            line_value(ROW_SPREAD, "SPREAD", (int8_t)result.spread, 0);
        jobs &= ~JOB_SPREAD;
    } else if (jobs & JOB_CURRENT) {
        line_value(ROW_CURRENT, "CURRENT", latency, 1);
        jobs &= ~JOB_CURRENT;
    } else if (jobs & JOB_PROMPT) {
        draw_prompt();
        jobs &= ~JOB_PROMPT;
    }
}

/* The song keeps playing from scene start to exit: restarting it mid-scene would cost the VBlank
 * ISR most of a frame (every channel starts at once). */
static void start_tapping(void)
{
    calib_reset(&calib);
    drawn = 0;
    wait = 0;
    state = TAPPING;
    input_flush();
}

static void finish(void)
{
    calib_result(&calib, &result);
    state = RESULT;
    wait = PROMPT_DELAY;
    jobs |= JOB_MEDIAN | JOB_SPREAD;
}

static void accept(void)
{
    settings_t s;

    latency = result.offset;
    s.latency_offset = latency;
    save_ok = settings_write(&s);
    state = SAVED;
    jobs |= JOB_CURRENT | JOB_PROMPT;
}

/* Global, not static: bankpack only assigns a bank to global b_ symbols. */
scene_t calibrate_scene(void) BANKED;

scene_t calibrate_scene(void) BANKED
{
    press_t press;
    uint8_t edges;

    scene_begin();
    CRITICAL { /* raw grading while calibrating (the ISR reads these) */
        saved_steps = tuning.timing_steps_per_beat;
        saved_hits = tuning.feedback_musical_hits;
        latency = (int8_t)tuning.timing_latency_offset;
        tuning.timing_steps_per_beat = 1;
        tuning.timing_latency_offset = 0;
        tuning.feedback_musical_hits = 0;
    }
    jobs = 0;
    text_print(1, ROW_TITLE, "CALIBRATE LATENCY");
    text_print(1, ROW_HELP, "TAP A ON EACH BEAT");
    text_print(1, ROW_HELP + 1, "OF THE DRUMS.");
    text_print(1, ROW_BACK, "START: BACK");
    line_value(ROW_CURRENT, "CURRENT", latency, 1);
    start_tapping();
    PLAY_SONG(CALIB_SONG); /* the clock waits for VBlank, i.e. scene_show */
    draw_taps();
    overlay_init(OVERLAY_X, OVERLAY_Y);
    scene_show();

    while (1) {
        vsync();
        overlay_update(); /* sprites first */

        edges = input_edges();
        if (edges & J_START)
            break;
        /* Menu buttons act on the state as it was before this frame's taps, so the last tap can't
         * also count as Accept. */
        if (wait) {
            if (--wait == 0)
                jobs |= JOB_PROMPT;
        } else if (state == RESULT && (edges & J_A)) {
            accept();
        } else if (state != TAPPING && (edges & J_B)) {
            start_tapping();
            jobs |= JOB_CLEAR_GRID | JOB_TAPS | JOB_MEDIAN | JOB_SPREAD | JOB_PROMPT;
        }
#ifdef DEBUG
        if (edges & J_SELECT)
            overlay_toggle();
#endif

        while (input_pop(&press)) {
            if (state != TAPPING || !(press.buttons & J_A))
                continue;
            if (calib_add(&calib, press.judgement.frames))
                finish();
            jobs |= JOB_TAPS;
        }
        run_job();
    }

    music_stop();
    CRITICAL {
        tuning.timing_steps_per_beat = saved_steps;
        tuning.feedback_musical_hits = saved_hits;
        tuning.timing_latency_offset = latency;
    }
    return SCENE_MENU;
}

/* Bank 0 entry point for main()'s scene table; the scene itself lives in a switchable bank. */
scene_t calibrate_run(void) NONBANKED
{
    return calibrate_scene();
}
