#include "board.h"
#include "demo.h"
#include "acceptance.h"
#include "stm32f4xx.h"

int main(void)
{
    uint8_t ch;
    board_init();
    board_startup_indication();
    demo_init();
    for (;;) {
        if (USART1->SR & USART_SR_RXNE) {
            ch=(uint8_t)USART1->DR;
            if (ch=='t') {
                demo_input('s');
                acceptance_run();
                demo_init();
            } else demo_input(ch);
        }
        demo_poll();
        /* Poll continuously: UART host lines arrive faster than 1 byte/ms. */
    }
}
