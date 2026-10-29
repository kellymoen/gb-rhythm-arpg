#ifndef CORE_BANKED_H
#define CORE_BANKED_H

/* CORE_BANKED marks a src/core function that lives in a switchable ROM bank on the Game Boy and is
 * called with a banked call. Bank 0 is nearly full, so portable game logic goes there unless measurement
 * says otherwise (docs/perf.md: the banked-call overhead is small next to the work). `__banked` is an SDCC
 * keyword, not a GBDK header, so this stays portable: the host build has no banks and drops it.
 *
 * Put it on the prototype and the definition, and open the .c file with
 *     #ifdef __SDCC
 *     #pragma bank 255
 *     #endif
 * A banked function's own ROM data is mapped while it runs; data in another bank is not, so pass RAM
 * copies (or bank 0 data) to it. */
#ifdef __SDCC
#define CORE_BANKED __banked
#else
#define CORE_BANKED
#endif

#endif
