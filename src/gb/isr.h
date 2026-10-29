#ifndef GB_ISR_H
#define GB_ISR_H

#include <stdint.h>

/* Install the VBlank handler: music + beat clock, then SFX, then input judging, then musical hits. */
void isr_init(void);

/* Musical hits (CONTEXT.md). Register writes stay in the VBlank ISR; scenes pick how hits are chosen.
 *
 * Scheduled (the default; the combat scene): the main loop schedules the hit of the combo step a
 * press became (combo_hit()), and the ISR plays it once both
 *   - dodge_grace frames have passed since the press with no other button pressed (a dodge plays no
 *     hit: the ISR checks the presses it saw itself, so a dodge the main loop has not read yet still
 *     cancels it), and
 *   - with feedback.quantize_hits, the beat clock has reached the step slot's start (an early press
 *     waits for its slot; an on-time or late one plays as soon as the first condition holds).
 * One hit is scheduled at a time: a new one replaces one that has not played.
 *
 * On press (the rhythm test): every non-OFFBEAT press plays HITS pitch sfx_hit_step at once, on the
 * press's own frame. scene_begin() switches back to scheduled. */
extern volatile uint8_t isr_hits_on_press;

/* Main loop: schedule HITS pitch `step` for a press made on input_frame `frame` with `buttons`,
 * judged against step slot `slot`. Call it on the frame the press is read. */
void isr_hit_schedule(uint8_t step, uint16_t slot, uint8_t frame, uint8_t buttons);

/* Main loop: drop the scheduled hit if it has not played. */
void isr_hit_cancel(void);

#endif
