#ifndef AUDIO_MUSIC_H
#define AUDIO_MUSIC_H

#include <stdint.h>

#include "audio/song.h"
#include "core/beat.h"

/* Our sound driver (ADR 0005). It owns the beat clock that all gameplay timing reads. */

/* Written by the VBlank ISR. The ISR reads it directly; the main loop uses music_now(). */
extern beat_clock_t music_clock;
extern uint8_t music_beats_per_bar;
extern uint16_t music_bpm; /* current tempo for display; tempo events update it (always < 256) */

/* Main loop: a consistent copy of the beat clock (the ISR may fire mid-read otherwise). */
void music_now(beat_clock_t *out);

void music_init(void);

/* Start a song from its bank, e.g. music_play(BANK(song_rhythmtest), &song_rhythmtest). */
void music_play(uint8_t bank, const song_t *song);
void music_stop(void);

/* Advance one frame: step the beat clock, run due events, apply vibrato. VBlank ISR only. */
void music_update(void);

/* Channel stealing, used by the SFX driver (sfx.c) from the VBlank ISR only. Bit `1 << CH_*` set:
 * the channel belongs to an effect, and the music advances there silently. */
extern uint8_t music_locked;

/* Silence a stolen channel and hand it back: the music retriggers it (duty, envelope, wave RAM) on
 * its next note there. */
void music_release(uint8_t ch);

/* The current song's musical hits: instrument index and HITS pitches (music_note_freq indices). */
extern uint8_t music_hit_instrument;
extern uint8_t music_hit_count;
extern uint8_t music_hits[HITS_MAX];

#endif
