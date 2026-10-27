#ifndef AUDIO_MUSIC_H
#define AUDIO_MUSIC_H

#include <stdint.h>

#include "audio/song.h"
#include "core/beat.h"

/* Our sound driver (ADR 0005). It owns the beat clock that all gameplay timing reads. */

/* Written by the VBlank ISR. The ISR reads it directly; the main loop uses music_now(). */
extern beat_clock_t music_clock;
extern uint8_t music_beats_per_bar;
extern uint16_t music_bpm;

/* Main loop: a consistent copy of the beat clock (the ISR may fire mid-read otherwise). */
void music_now(beat_clock_t *out);

void music_init(void);

/* Start a song from its bank, e.g. music_play(BANK(song_rhythmtest), &song_rhythmtest). */
void music_play(uint8_t bank, const song_t *song);
void music_stop(void);

/* Advance one frame: step the beat clock, run due events, apply vibrato. VBlank ISR only. */
void music_update(void);

/* Musical hit: steal P2 and play the song's hit instrument at its n-th hit pitch (wrapping).
 * VBlank ISR only, so it can't race music_update's register writes. */
void music_hit(uint16_t n);

#endif
