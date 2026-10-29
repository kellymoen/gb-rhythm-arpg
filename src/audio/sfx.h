#ifndef AUDIO_SFX_H
#define AUDIO_SFX_H

#include <stdint.h>

/* Sound effects (ADR 0005, 0006). Each effect is authored as register-level steps in
 * assets/sfx/<name>.toml (live-editable in the feel lab; format in docs/sfx.md) and converted to
 * SFX_<NAME> ids in the generated sfx.h (#include "sfx.h" from a scene). An effect declares a channel
 * and a priority: it steals that channel from the music (or from a lower-priority effect) and the
 * music resumes on its next note. */

/* Musical hits play on P2 at this priority: effects at 8+ on P2 cut them, lower ones are dropped
 * while one rings (PROVISIONAL). */
#define SFX_HIT_PRIORITY 8

/* Called by isr_init() before the VBlank handler is installed. */
void sfx_init(void);

/* Main loop: request an effect. It starts in the next VBlank (no register writes here, so it can't
 * race the driver). A request for a busy channel only wins on equal or higher priority. Up to four
 * requests per frame; more are dropped. */
void sfx_play(uint8_t id);

/* VBlank ISR only, right after music_update(): start requested effects and step running ones. */
void sfx_update(void);

/* VBlank ISR only: play a musical hit now (the press's own frame) with the song's hit instrument at
 * HITS pitch sfx_hit_step (wrapping). Does nothing if the song has no HITS track. */
void sfx_hit(void);

/* Musical hits: the string step (0-based) whose pitch the next on-beat press plays from the song's
 * HITS set. The main loop sets it from combo events; the ISR reads it when it plays the hit. */
extern volatile uint8_t sfx_hit_step;

#endif
