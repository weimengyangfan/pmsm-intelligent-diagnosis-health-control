/* Independent bring-up firmware: no SPI, UART, SysTick, or interrupts needed.
   Select STM32F407_LED_SelfTest in Keil. Both LEDs are active LOW. */
#include "stm32f4xx.h"

volatile uint32_t g_led_selftest_count;

static void visible_delay(void)
{
    volatile uint32_t i;
    /* Visual delay only; intentionally does not use clocks/interrupt services. */
    for (i = 0; i < 600000UL; ++i) __NOP();
}

int main(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOFEN;
    (void)RCC->AHB1ENR;
    GPIOF->BSRR = (1UL << 9) | (1UL << 10);
    GPIOF->OTYPER &= ~((1UL << 9) | (1UL << 10));
    GPIOF->PUPDR &= ~((3UL << 18) | (3UL << 20));
    GPIOF->MODER = (GPIOF->MODER & ~((3UL << 18) | (3UL << 20))) |
                    (1UL << 18) | (1UL << 20);
    for (;;) {
        GPIOF->BSRR = (1UL << 25) | (1UL << 10); /* Red on, green off. */
        visible_delay();
        GPIOF->BSRR = (1UL << 9) | (1UL << 26); /* Red off, green on. */
        visible_delay();
        ++g_led_selftest_count;
    }
}
