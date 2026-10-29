#include <gbdk/platform.h>
#include <string.h>

#include "audio/music.h"
#include "audio/sfx.h"
#include "audio/sfxdata.h"
#include "tuning.h"

/* Stays in bank 0 (it runs in the VBlank ISR and switches to the effect data's bank).
 *
 * Each channel is owned by the music (priority 0) or by one running effect. An effect that starts
 * sets the channel's bit in music_locked, so the music advances there silently; when its last step
 * ends, music_release() silences the channel and the music's next note there retriggers it.
 * Musical hits are effects too: one synthesized step on P2 at SFX_HIT_PRIORITY.
 *
 * No 16-bit multiply/divide here: pointers step by addition and the hit pitch wraps by subtraction. */

#define QUEUE_SIZE 4 /* power of two */

sfx_chan_t sfx_chan[4];
volatile uint8_t sfx_hit_step;

static uint8_t queue[QUEUE_SIZE];
static volatile uint8_t q_head; /* written by the main loop only */
static volatile uint8_t q_tail; /* written by the ISR only */
static sfx_step_t hit_step;     /* RAM, so it plays whatever bank is switched in */

static const uint8_t chan_bit[4] = { 1, 2, 4, 8 };

/* The step being applied and the channel's running state, copied into statics: SDCC addresses
 * these directly, which is several times cheaper than going through struct pointers. */
static sfx_step_t st;
static union {
    uint16_t w;
    struct {
        uint8_t lo, hi;
    } b;
} freq;
static uint8_t reg1, len_on, env;

#define PULSE_REGS(N1, N2, N3, N4)                         \
    if (st.volume != SFX_KEEP) {                           \
        N1 = reg1;                                         \
        N2 = env;                                          \
        N3 = freq.b.lo;                                    \
        N4 = 0x80 | len_on | freq.b.hi;                    \
    } else {                                               \
        if (st.duty != SFX_KEEP)                           \
            N1 = reg1;                                     \
        if (st.pitch_hi != SFX_KEEP) {                     \
            N3 = freq.b.lo;                                \
            N4 = len_on | freq.b.hi; /* no retrigger */    \
        }                                                  \
    }

static void apply_pulse(uint8_t ch)
{
    if (st.duty != SFX_KEEP)
        reg1 = (uint8_t)(st.duty << 6) | (reg1 & 0x3F);
    if (st.pitch_hi != SFX_KEEP) {
        freq.b.lo = st.pitch_lo;
        freq.b.hi = st.pitch_hi;
    }
    if (st.volume != SFX_KEEP) {
        if (st.length) {
            len_on = 0x40;
            reg1 = (reg1 & 0xC0) | (uint8_t)(64 - st.length);
        } else {
            len_on = 0;
            reg1 &= 0xC0;
        }
        env = (uint8_t)(st.volume << 4) | (uint8_t)(st.env_dir << 3) | st.env_pace;
    }
    if (ch == CH_P1) {
        if (st.volume != SFX_KEEP)
            NR10_REG = (uint8_t)(st.sweep_pace << 4) | (uint8_t)(st.sweep_dir << 3) | st.sweep_step;
        PULSE_REGS(NR11_REG, NR12_REG, NR13_REG, NR14_REG)
    } else {
        PULSE_REGS(NR21_REG, NR22_REG, NR23_REG, NR24_REG)
    }
}

static void apply_wave(sfx_chan_t *c)
{
    const uint8_t *w;
    uint8_t i, v;

    if (st.pitch_hi != SFX_KEEP) {
        freq.b.lo = st.pitch_lo;
        freq.b.hi = st.pitch_hi;
    }
    if (st.volume == SFX_KEEP) {
        if (st.pitch_hi != SFX_KEEP) {
            NR33_REG = freq.b.lo;
            NR34_REG = len_on | freq.b.hi;
        }
        return;
    }
    /* DAC off first: wave RAM is only safely writable then, and retriggering a playing wave
     * channel corrupts wave RAM on the DMG. */
    NR30_REG = 0;
    i = st.env_dir; /* the step's wave shape */
    if (i != SFX_KEEP && (uint8_t)(c->wave_base + i) != c->wave) {
        c->wave = c->wave_base + i;
        w = &sfx_waves[0][0] + ((uint16_t)c->wave << 4);
        for (i = 0; i < 16; i++)
            AUD3WAVE[i] = w[i];
    }
    len_on = st.length ? 0x40 : 0;
    v = st.volume;
    NR30_REG = 0x80;
    NR31_REG = (uint8_t)(0 - st.length);
    NR32_REG = v >= 12 ? 0x20 : v >= 6 ? 0x40 : v ? 0x60 : 0; /* 100%, 50%, 25%, mute */
    NR33_REG = freq.b.lo;
    NR34_REG = 0x80 | len_on | freq.b.hi;
}

static void apply_noise(void)
{
    if (st.duty != SFX_KEEP) /* noise_shift */
        reg1 = (reg1 & 0x0F) | (uint8_t)(st.duty << 4);
    if (st.pitch_lo != SFX_KEEP) /* noise_width: 7 sets the 7-bit LFSR */
        reg1 = (reg1 & 0xF7) | ((st.pitch_lo & 8) ? 0 : 8);
    if (st.pitch_hi != SFX_KEEP) /* noise_divisor */
        reg1 = (reg1 & 0xF8) | (st.pitch_hi & 7);
    if (st.volume == SFX_KEEP) {
        NR43_REG = reg1;
        return;
    }
    len_on = st.length ? 0x40 : 0;
    NR41_REG = st.length ? (uint8_t)(64 - st.length) : 0;
    NR42_REG = (uint8_t)(st.volume << 4) | (uint8_t)(st.env_dir << 3) | st.env_pace;
    NR43_REG = reg1;
    NR44_REG = 0x80 | len_on;
}

/* Start the next step, or hand the channel back after the last one. */
static void next_step(uint8_t ch, sfx_chan_t *c)
{
    if (!c->left) {
        c->priority = 0;
        music_release(ch);
        return;
    }
    memcpy(&st, c->step, sizeof st);
    c->step++;
    c->left--;
    c->timer = st.frames;
    c->slide = st.slide;
    freq.w = c->freq;
    reg1 = c->reg1;
    len_on = c->len_on;
    if (ch == CH_NOISE)
        apply_noise();
    else if (ch == CH_WAVE)
        apply_wave(c);
    else
        apply_pulse(ch);
    c->freq = freq.w;
    c->reg1 = reg1;
    c->len_on = len_on;
}

static void slide(uint8_t ch, sfx_chan_t *c)
{
    freq.w = c->freq + (int16_t)c->slide;
    if (freq.w > 2047) /* ran off either end of the period range */
        freq.w = c->slide < 0 ? 0 : 2047;
    c->freq = freq.w;
    freq.b.hi |= c->len_on;
    if (ch == CH_P1) {
        NR13_REG = freq.b.lo;
        NR14_REG = freq.b.hi;
    } else if (ch == CH_P2) {
        NR23_REG = freq.b.lo;
        NR24_REG = freq.b.hi;
    } else {
        NR33_REG = freq.b.lo;
        NR34_REG = freq.b.hi;
    }
}

static void begin(uint8_t ch, uint8_t priority, const sfx_step_t *steps, uint8_t count, uint8_t wave_base)
{
    sfx_chan_t *c = &sfx_chan[ch];

    if (priority < c->priority)
        return; /* a more important effect holds the channel */
    music_locked |= chan_bit[ch];
    c->priority = priority;
    c->step = steps;
    c->left = count;
    c->reg1 = ch == CH_NOISE ? 0 : 0x80; /* 50% duty until a step says otherwise */
    c->len_on = 0;
    c->freq = 0;
    c->wave = 0xFF;
    c->wave_base = wave_base;
    next_step(ch, c);
}

void sfx_init(void)
{
    q_head = q_tail = 0;
    sfx_hit_step = 0;
    memset(sfx_chan, 0, sizeof sfx_chan);
#ifdef DEBUG
    sfx_reset();
#endif
}

void sfx_play(uint8_t id)
{
    uint8_t h = q_head;

    if ((uint8_t)(h - q_tail) == QUEUE_SIZE)
        return; /* four requests in one frame already */
    queue[h & (QUEUE_SIZE - 1)] = id;
    q_head = h + 1;
}

void sfx_update(void)
{
    uint8_t ch, saved;
    sfx_chan_t *c;
    const sfx_t *e;

    if (!music_locked && q_tail == q_head)
        return;
    saved = CURRENT_BANK;
    SWITCH_ROM(BANK(sfx_data));
    for (ch = 0, c = sfx_chan; ch < 4; ch++, c++) {
        if (!c->priority)
            continue;
        if (--c->timer == 0)
            next_step(ch, c);
        else if (c->slide && ch != CH_NOISE)
            slide(ch, c);
    }
    while (q_tail != q_head) {
        ch = queue[q_tail & (QUEUE_SIZE - 1)];
        q_tail++;
        if (ch < sfx_count) {
            e = sfx_index[ch];
            begin(e->channel, e->priority, e->steps, e->count, e->wave_base);
        }
    }
    SWITCH_ROM(saved);
}

void sfx_hit(uint8_t n)
{
    const instrument_t *ins = &music_instruments[music_hit_instrument];
    uint8_t note;

    if (!music_hit_count)
        return;
    while (n >= music_hit_count)
        n -= music_hit_count;
    note = music_hits[n];
    freq.w = music_note_freq[note];
    hit_step.frames = (uint8_t)tuning.feedback_musical_hit_frames;
    hit_step.volume = (uint8_t)tuning.feedback_musical_hit_volume;
    hit_step.env_dir = ins->env >> 3;
    hit_step.env_pace = ins->env & 7;
    hit_step.duty = ins->duty;
    hit_step.pitch_lo = freq.b.lo;
    hit_step.pitch_hi = freq.b.hi;
    begin(CH_P2, SFX_HIT_PRIORITY, &hit_step, 1, 0);
}
