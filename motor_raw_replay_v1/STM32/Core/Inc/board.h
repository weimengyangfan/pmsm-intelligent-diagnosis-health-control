#ifndef BOARD_H
#define BOARD_H
#include <stdint.h>
void board_init(void);
void board_startup_indication(void);
void board_delay_ms(uint32_t ms);
void board_led_result(int success);
void board_puts(const char *text);
void board_hex8(uint8_t value);
int board_spi_frame(const uint8_t tx[4], uint8_t rx[4]);
int board_select_backend(unsigned hardware);
uint32_t board_millis(void);
#endif
