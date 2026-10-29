#include <gb/gb.h>

#include "audio/music.h"
#include "audio/sfx.h"
#include "gb/input.h"
#include "gb/isr.h"
#include "tuning.h"

/* Stays in bank 0: the VBlank handler and what it reads. */

volatile uint8_t isr_hits_on_press;

/* The scheduled hit. The main loop writes the fields while hit_state is HIT_NONE, then sets it. */
enum { HIT_NONE, HIT_HELD, HIT_DUE };
static volatile uint8_t hit_state;
static uint8_t hit_step, hit_frame, hit_buttons, hit_tick;
static uint16_t hit_beat;

/* Buttons newly pressed on each of the last 8 frames, at input_frame & 7: what a held hit checks
 * for a dodge (dodge_grace <= 6). */
#define RECENT 8
static uint8_t recent[RECENT];

/* HIT_HELD: once dodge_grace frames have passed, look at the presses after the hit's own, in order,
 * the way the combo matcher does: another button first means a dodge (no hit); the same button
 * first means the held press landed. Then HIT_DUE waits for the slot. */
static void hit_update(void)
{
    uint8_t grace = (uint8_t)tuning.input_dodge_grace, d = input_frame - hit_frame, f, b;

    if (hit_state == HIT_HELD) {
        if (d < grace)
            return;
        if (d < RECENT) { /* older entries are gone: the main loop stalled; it cancels a dodge itself */
            for (f = hit_frame; grace; grace--) {
                b = recent[++f & (RECENT - 1)];
                if (b & (uint8_t)~hit_buttons) {
                    hit_state = HIT_NONE;
                    return;
                }
                if (b)
                    break;
            }
        }
        hit_state = HIT_DUE;
    }
    if (music_clock.beat < hit_beat || (music_clock.beat == hit_beat && music_clock.tick < hit_tick))
        return;
    hit_state = HIT_NONE;
    if (tuning.feedback_musical_hits)
        sfx_hit(hit_step);
}

/* Audio first (fixed cost at the top of VBlank), then the press, then musical hits. */
static void vblank(void)
{
    const press_t *p;

    music_update();
    sfx_update();
    p = input_poll();
    recent[input_frame & (RECENT - 1)] = p ? p->buttons : 0;
    if (p && isr_hits_on_press && tuning.feedback_musical_hits && p->judgement.grade != GRADE_OFFBEAT)
        sfx_hit(sfx_hit_step);
    if (hit_state)
        hit_update();
}

void isr_hit_schedule(uint8_t step, uint16_t slot, uint8_t frame, uint8_t buttons)
{
    beat_clock_t now;
    uint16_t beat, tick = 0;

    music_now(&now);
    beat = now.beat;
    if (tuning.feedback_quantize_hits) { /* the slot's start: at most a slot ahead, so a short loop */
        tick = now.tick + beat_ticks_until_slot(&now, slot);
        while (tick >= BEAT_TICKS) {
            tick -= BEAT_TICKS;
            beat++;
        }
    } else {
        tick = now.tick; /* reached already */
    }
    hit_state = HIT_NONE;
    hit_step = step;
    hit_frame = frame;
    hit_buttons = buttons;
    hit_beat = beat;
    hit_tick = (uint8_t)tick;
    hit_state = HIT_HELD;
}

void isr_hit_cancel(void)
{
    hit_state = HIT_NONE;
}

void isr_init(void)
{
    sfx_init();
    CRITICAL {
        add_VBL(vblank);
    }
}
