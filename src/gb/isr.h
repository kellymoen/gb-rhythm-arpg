#ifndef GB_ISR_H
#define GB_ISR_H

/* Install the VBlank handler: music + beat clock, then SFX, then input judging, then the musical
 * hit for a non-OFFBEAT press. */
void isr_init(void);

#endif
