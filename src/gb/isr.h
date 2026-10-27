#ifndef GB_ISR_H
#define GB_ISR_H

/* Install the VBlank handler: music + beat clock, then input judging, then musical hits. */
void isr_init(void);

#endif
