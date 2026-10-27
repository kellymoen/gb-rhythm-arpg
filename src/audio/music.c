#include <gbdk/platform.h>
#include <string.h>

#include "audio/music.h"

/* Stays in bank 0 so it can switch to the song's bank from the ISR. */

#define HIT_FRAMES 10

typedef struct {
    const uint8_t *pos;
    const uint8_t *loop;
    int16_t wait; /* song ticks until the next event */
    uint8_t note; /* music_note_freq index (noise: drum instrument), or NOTE_INDEX_NONE */
    uint8_t vol;
    uint8_t instr;
    uint8_t duty;
    int8_t bend;
    uint8_t vib;
} chan_t;

static chan_t chans[CH_COUNT];
static uint8_t song_bank;
static volatile uint8_t playing;
static uint8_t loaded_wave = 0xFF;
static uint8_t lfo;
static uint8_t hit_timer;
static uint8_t hit_instrument;
static uint8_t hit_count;
static uint8_t hits[HITS_MAX];

beat_clock_t music_clock;
uint8_t music_beats_per_bar;
uint16_t music_bpm;

static uint16_t chan_freq(const chan_t *c)
{
    uint16_t f = music_note_freq[c->note];
    uint8_t other;

    if (c->bend > 0) {
        other = c->note + 2 < NOTE_COUNT ? c->note + 2 : NOTE_COUNT - 1;
        f += (uint16_t)((music_note_freq[other] - f) * (uint8_t)c->bend) >> 6;
    } else if (c->bend < 0) {
        other = c->note >= 2 ? c->note - 2 : 0;
        f -= (uint16_t)((f - music_note_freq[other]) * (uint8_t)(-c->bend)) >> 6;
    }
    return f;
}

/* Write a pitch to a tone channel without retriggering it. */
static void write_freq(uint8_t ch, uint16_t f)
{
    if (ch == CH_P1) {
        NR13_REG = (uint8_t)f;
        NR14_REG = (uint8_t)(f >> 8);
    } else if (ch == CH_P2) {
        if (hit_timer)
            return;
        NR23_REG = (uint8_t)f;
        NR24_REG = (uint8_t)(f >> 8);
    } else if (ch == CH_WAVE) {
        NR33_REG = (uint8_t)f;
        NR34_REG = (uint8_t)(f >> 8);
    }
}

static void load_wave(uint8_t w)
{
    uint8_t i;

    NR30_REG = 0; /* wave RAM is only safely writable with the DAC off */
    for (i = 0; i < 16; i++)
        AUD3WAVE[i] = music_waves[w][i];
    loaded_wave = w;
}

static void note_on(uint8_t ch, const chan_t *c)
{
    const instrument_t *ins = &music_instruments[ch == CH_NOISE ? c->note : c->instr];
    uint16_t f;

    switch (ch) {
    case CH_P1:
        f = chan_freq(c);
        NR10_REG = 0;
        NR11_REG = c->duty << 6;
        NR12_REG = (c->vol << 4) | ins->env;
        NR13_REG = (uint8_t)f;
        NR14_REG = 0x80 | (uint8_t)(f >> 8);
        break;
    case CH_P2:
        if (hit_timer)
            break;
        f = chan_freq(c);
        NR21_REG = c->duty << 6;
        NR22_REG = (c->vol << 4) | ins->env;
        NR23_REG = (uint8_t)f;
        NR24_REG = 0x80 | (uint8_t)(f >> 8);
        break;
    case CH_WAVE:
        if (ins->param != loaded_wave)
            load_wave(ins->param);
        f = chan_freq(c);
        NR30_REG = 0x80;
        NR32_REG = (c->vol >= 12 ? 1 : c->vol >= 6 ? 2 : 3) << 5; /* 100%, 50%, 25% */
        NR33_REG = (uint8_t)f;
        NR34_REG = 0x80 | (uint8_t)(f >> 8);
        break;
    case CH_NOISE:
        NR42_REG = (c->vol << 4) | ins->env;
        NR43_REG = ins->param;
        NR44_REG = 0x80;
        break;
    }
}

static void note_off(uint8_t ch)
{
    if (ch == CH_P1)
        NR12_REG = 0;
    else if (ch == CH_P2 && !hit_timer)
        NR22_REG = 0;
    else if (ch == CH_WAVE)
        NR32_REG = 0;
}

static void run_event(uint8_t ch, chan_t *c)
{
    uint8_t op = *c->pos++;

    if (op <= EV_NOTE_MAX) {
        c->note = op;
        c->vol = *c->pos++;
        note_on(ch, c);
    } else {
        switch (op) {
        case EV_OFF:
            note_off(ch);
            c->note = NOTE_INDEX_NONE;
            break;
        case EV_INSTR:
            c->instr = *c->pos++;
            c->duty = music_instruments[c->instr].duty;
            break;
        case EV_DUTY:
            c->duty = *c->pos++;
            if (c->note != NOTE_INDEX_NONE) {
                if (ch == CH_P1)
                    NR11_REG = c->duty << 6;
                else if (ch == CH_P2 && !hit_timer)
                    NR21_REG = c->duty << 6;
            }
            break;
        case EV_BEND:
            c->bend = (int8_t)*c->pos++;
            if (c->note != NOTE_INDEX_NONE)
                write_freq(ch, chan_freq(c));
            break;
        case EV_VIB:
            c->vib = *c->pos++;
            break;
        case EV_TEMPO:
            music_clock.rate = c->pos[0] | ((uint16_t)c->pos[1] << 8);
            c->pos += 2;
            break;
        case EV_LOOP:
            c->loop = c->pos;
            break;
        case EV_END:
            c->pos = c->loop;
            break;
        default: /* EV_NOP */
            break;
        }
    }
    c->wait += *c->pos++;
}

static void vibrato(void)
{
    uint8_t ch;
    int8_t t;
    chan_t *c;

    lfo++;
    t = (lfo & 0x08) ? 7 - (lfo & 7) : (lfo & 7); /* triangle 0..7..0, 16 frames */
    t -= 4;
    for (ch = CH_P1; ch <= CH_WAVE; ch++) {
        c = &chans[ch];
        if (c->vib && c->note != NOTE_INDEX_NONE)
            write_freq(ch, chan_freq(c) + ((t * (int8_t)c->vib) >> 2));
    }
}

void music_init(void)
{
    NR52_REG = 0x80;
    NR50_REG = 0x77;
    NR51_REG = 0xFF;
    music_stop();
}

void music_play(uint8_t bank, const song_t *song)
{
    uint8_t saved = CURRENT_BANK;
    uint8_t ch;
    chan_t *c;

    playing = 0;
    SWITCH_ROM(bank);
    for (ch = 0; ch < CH_COUNT; ch++) {
        c = &chans[ch];
        c->pos = song->streams[ch];
        c->loop = c->pos;
        c->wait = *c->pos++;
        c->note = NOTE_INDEX_NONE;
        c->instr = 0;
        c->duty = 2;
        c->bend = 0;
        c->vib = 0;
    }
    beat_clock_start(&music_clock, song->rate);
    music_beats_per_bar = song->beats_per_bar;
    music_bpm = song->bpm;
    hit_instrument = song->hit_instrument;
    hit_count = song->hit_count;
    memcpy(hits, song->hits, HITS_MAX);
    SWITCH_ROM(saved);
    song_bank = bank;
    playing = 1;
}

void music_stop(void)
{
    playing = 0;
    NR12_REG = 0;
    NR22_REG = 0;
    NR32_REG = 0;
    NR42_REG = 0;
}

void music_update(void)
{
    uint8_t saved, ch, ticks;
    chan_t *c;

    if (hit_timer && --hit_timer == 0)
        NR22_REG = 0; /* hand P2 back; the music's next P2 note retriggers it */
    if (!playing)
        return;

    saved = CURRENT_BANK;
    SWITCH_ROM(song_bank);
    ticks = beat_clock_step(&music_clock);
    for (ch = 0; ch < CH_COUNT; ch++) {
        c = &chans[ch];
        c->wait -= ticks;
        while (c->wait <= 0)
            run_event(ch, c);
    }
    SWITCH_ROM(saved);
    vibrato();
}

void music_now(beat_clock_t *out)
{
    CRITICAL {
        *out = music_clock;
    }
}

void music_hit(uint16_t n)
{
    const instrument_t *ins = &music_instruments[hit_instrument];
    uint16_t f;

    if (!hit_count)
        return;
    f = music_note_freq[hits[(uint8_t)n % hit_count]]; /* 8-bit modulo: this runs in the ISR */
    hit_timer = HIT_FRAMES;
    NR21_REG = ins->duty << 6;
    NR22_REG = 0xF0 | ins->env;
    NR23_REG = (uint8_t)f;
    NR24_REG = 0x80 | (uint8_t)(f >> 8);
}
