#include <gb/gb.h>

#include "audio/music.h"
#include "gb/input.h"

#define QUEUE_SIZE 8 /* power of two */

volatile uint8_t input_held;
volatile uint8_t input_frame;

#ifdef DEBUG
press_log_t press_log[PRESS_LOG_SIZE];
volatile uint8_t press_log_head;
#endif

static press_t queue[QUEUE_SIZE];
static volatile uint8_t head; /* written by the ISR only */
static volatile uint8_t tail; /* written by the main loop only */

const press_t *input_poll(void)
{
    uint8_t now = joypad();
    uint8_t pressed = now & ~input_held & (J_A | J_B);
    press_t *p;

    input_held = now;
    input_frame++;
    if (!pressed || (uint8_t)(head - tail) == QUEUE_SIZE)
        return 0;
    p = &queue[head & (QUEUE_SIZE - 1)];
    p->buttons = pressed;
    p->held = now;
    p->frame = input_frame;
    beat_judge(&music_clock, &p->judgement);
#ifdef DEBUG
    {
        press_log_t *l = &press_log[press_log_head & (PRESS_LOG_SIZE - 1)];
        l->frame = input_frame;
        l->buttons = pressed;
        l->grade = (uint8_t)p->judgement.grade;
        l->frames = p->judgement.frames;
        press_log_head++;
    }
#endif
    head++;
    return p;
}

void input_flush(void)
{
    tail = head;
}

uint8_t input_pop(press_t *out)
{
    if (tail == head)
        return 0;
    *out = queue[tail & (QUEUE_SIZE - 1)];
    tail++;
    return 1;
}

uint8_t input_edges(void)
{
    static uint8_t prev;
    uint8_t now = input_held;
    uint8_t edges = now & ~prev;

    prev = now;
    return edges;
}
