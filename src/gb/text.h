#ifndef GB_TEXT_H
#define GB_TEXT_H

#include <stdint.h>

/* BG text from assets/ui/font.png. Glyph order (contract with tools/gbtools/placeholders.py):
 *   " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-.:/!?%><"   Lowercase prints as uppercase. */

void text_init(void);

/* Print at tile (x, y) on the background. Unknown characters print as '?'. */
void text_print(uint8_t x, uint8_t y, const char *s);

/* Print `v` right-aligned in `width` columns; `sign` forces a leading '+' on positive values. */
void text_print_int(uint8_t x, uint8_t y, int16_t v, uint8_t width, uint8_t sign);

void text_clear(uint8_t x, uint8_t y, uint8_t width);

#endif
