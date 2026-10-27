#include <gb/gb.h>

#include "audio/music.h"
#include "gb/input.h"

#define QUEUE_SIZE 8 /* power of two */

volatile uint8_t input_held;

static press_t queue[QUEUE_SIZE];
static volatile uint8_t head; /* written by the ISR only */
static volatile uint8_t tail; /* written by the main loop only */

const press_t *input_poll(void)
{
    uint8_t now = joypad();
    uint8_t pressed = now & ~input_held & (J_A | J_B);
    press_t *p;

    input_held = now;
    if (!pressed || (uint8_t)(head - tail) == QUEUE_SIZE)
        return 0;
    p = &queue[head & (QUEUE_SIZE - 1)];
    p->buttons = pressed;
    beat_judge(&music_clock, &p->judgement);
    head++;
    return p;
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
