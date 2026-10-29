#ifndef AUDIO_SONG_H
#define AUDIO_SONG_H

#include <stdint.h>

/* Song data layout shared by tools/gbtools/music.py and the driver (ADR 0005). Keep them in sync. */

enum { CH_P1, CH_P2, CH_WAVE, CH_NOISE, CH_TEMPO, CH_COUNT };

/* A stream is <delta> followed by repeated <event><delta>, where delta is the number of song ticks
 * to wait before the next event. EV_END has no delta: playback continues from the loop point. */
#define EV_NOTE_MAX 0x7F /* 0x00..0x7F: NOTE <volume 0..15>; byte is a note_freq index (noise: drum) */
#define EV_OFF 0x80
#define EV_INSTR 0x81 /* <instrument index> */
#define EV_DUTY 0x82  /* <0..3> */
#define EV_BEND 0x83  /* <int8, 1/32 semitone, -64..64> */
#define EV_VIB 0x84   /* <depth 0..15> */
#define EV_TEMPO 0x85 /* <rate lo> <rate hi> <bpm>: rate is 8.8 ticks per frame, bpm for display */
#define EV_LOOP 0x86
#define EV_END 0x87
#define EV_NOP 0x88 /* padding for waits longer than 255 ticks */

enum { INSTR_PULSE, INSTR_WAVE, INSTR_NOISE };

typedef struct {
    uint8_t kind;
    uint8_t duty;  /* pulse: 0..3 (12.5%, 25%, 50%, 75%) */
    uint8_t env;   /* NRx2 low nibble: direction << 3 | pace (volume comes from the note) */
    uint8_t param; /* wave: index into music_waves; noise: NR43 value */
} instrument_t;

#define HITS_MAX 16
#define NOTE_COUNT 72 /* music_note_freq[0] is MIDI note 36 (C2) on the pulse channels */
#define NOTE_INDEX_NONE 0xFF

typedef struct {
    const uint8_t *streams[CH_COUNT];
    uint16_t rate; /* initial tempo, 8.8 ticks per frame */
    uint16_t bpm;  /* initial tempo, for display */
    uint8_t beats_per_bar;
    uint8_t hit_instrument;
    uint8_t hit_count;
    uint8_t hits[HITS_MAX]; /* note_freq indices that musical hits may play */
} song_t;

extern const uint16_t music_note_freq[NOTE_COUNT];
extern const instrument_t music_instruments[];
extern const uint8_t music_waves[][16];

#endif
