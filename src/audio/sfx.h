#ifndef AUDIO_SFX_H
#define AUDIO_SFX_H

#include <stdint.h>

/* Sound effects (ADR 0005, 0006). Each effect is authored as register-level steps in
 * assets/sfx/<name>.toml (live-editable in the feel lab) and converted to SFX_<NAME> ids in the
 * generated sfx.h. An effect declares a channel and a priority: it steals that channel from the
 * music (or from a lower-priority effect) and the music resumes on its next note. */

void sfx_init(void);

/* Main loop: request an effect. It starts in the next VBlank (no register writes here, so it can't
 * race the driver). A request for a busy channel only wins on equal or higher priority. */
void sfx_play(uint8_t id);

/* VBlank ISR only, right after music_update(): start requested effects and step running ones. */
void sfx_update(void);

/* Musical hits: the string step (0-based) whose pitch the next on-beat press plays from the song's
 * HITS set. The main loop sets it from combo events; the ISR reads it when it plays the hit. */
extern volatile uint8_t sfx_hit_step;

#endif
