#ifndef AUDIO_SFXDATA_H
#define AUDIO_SFXDATA_H

#include <gbdk/platform.h>
#include <stdint.h>

/* Sound-effect data layout shared by tools/gbtools/sfx.py, the driver (sfx.c) and the feel lab's
 * descriptor (build/gen/sfx.lab.json). Keep them in sync. Author guide: docs/sfx.md.
 *
 * An effect is a list of steps on one channel. Each step lasts `frames` VBlanks. A step whose
 * `volume` is set triggers the channel (a new note: envelope, length, sweep, pitch); a step without
 * it changes the running sound (pitch, duty, noise) without retriggering. Every field is one byte so
 * the lab can edit it in place; fields left out of the TOML hold SFX_KEEP (keep the running value). */

#define SFX_MAX_STEPS 16 /* fixed so the lab can add steps live */
#define SFX_WAVES_MAX 4  /* wave shapes per WAVE effect */
#define SFX_KEEP 0xFF

typedef struct {
    uint8_t frames;   /* 1..255 */
    uint8_t volume;   /* 0..15 triggers the channel; SFX_KEEP changes the running sound */
    uint8_t env_dir;  /* trigger: 0 down, 1 up.          WAVE: wave (index into the effect's waves) */
    uint8_t env_pace; /* trigger: 0..7 (0 = hold) */
    uint8_t length;   /* trigger: hardware cut after length/256 s, 0 = off (pulse/noise 1..64, WAVE 1..255) */
    uint8_t duty;     /* pulse: 0..3.                    NOISE: noise_shift 0..15 */
    uint8_t pitch_lo; /* pulse/WAVE: period 0..2047, hi = SFX_KEEP to keep. NOISE: noise_width 0 (15-bit) / 1 (7-bit) */
    uint8_t pitch_hi; /*                                 NOISE: noise_divisor 0..7 */
    int8_t slide;     /* pulse/WAVE: period added every frame after the step's first */
    uint8_t sweep_pace; /* P1 trigger: NR10 */
    uint8_t sweep_dir;  /* 0 up, 1 down */
    uint8_t sweep_step;
} sfx_step_t;

typedef struct {
    uint8_t channel;   /* CH_P1..CH_NOISE (song.h) */
    uint8_t priority;  /* 1..15: steals a channel playing music or an effect of equal or lower priority */
    uint8_t count;     /* steps used, 1..SFX_MAX_STEPS */
    uint8_t wave_base; /* WAVE: index of the effect's first shape in sfx_waves */
    sfx_step_t steps[SFX_MAX_STEPS];
} sfx_t;

/* Generated in build/gen/sfx_data.c (banked; read with BANK(sfx_data) switched in). */
BANKREF_EXTERN(sfx_data)
extern const uint8_t sfx_count;
extern const sfx_t *const sfx_index[]; /* by SFX_<NAME> id */
extern const uint8_t sfx_waves[][16];
#ifdef DEBUG
extern sfx_t sfx_table[]; /* RAM copy the feel lab edits (symbol _sfx_table) */
void sfx_reset(void) BANKED; /* copy the defaults into sfx_table */
#endif

/* Per-channel playback state, exported (as sfx_chan) for the ROM tests and the lab. */
typedef struct {
    const sfx_step_t *step; /* the next step */
    uint8_t priority;       /* 0: the music owns the channel */
    uint8_t left;           /* steps after the current one */
    uint8_t timer;          /* frames left in the current step */
    int8_t slide;
    uint16_t freq;          /* running period (pulse/WAVE) */
    uint8_t reg1;           /* pulse: NRx1 duty|length. NOISE: NR43 */
    uint8_t len_on;         /* 0x40 when the hardware length counter is enabled */
    uint8_t wave;           /* WAVE: shape loaded in wave RAM (sfx_waves index), 0xFF = none */
    uint8_t wave_base;
} sfx_chan_t;

extern sfx_chan_t sfx_chan[4];

#endif
