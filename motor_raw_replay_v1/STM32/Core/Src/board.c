#include "board.h"
#include "stm32f4xx.h"

static volatile uint32_t ticks;
static unsigned hardware_backend;
volatile uint32_t g_board_stage;
volatile uint32_t g_uart_timeouts;
void SysTick_Handler(void) { ++ticks; }

/* Cortex-M4 cycle counter: delays/timeouts do not depend on interrupt delivery.
   All intervals below are <= 500ms, well within the 32-bit wrap interval. */
static int elapsed_ms(uint32_t start, uint32_t ms)
{
    return (uint32_t)(DWT->CYCCNT - start) >= (SystemCoreClock / 1000UL) * ms;
}

void board_delay_ms(uint32_t ms)
{
    while (ms != 0) {
        uint32_t interval = ms > 500 ? 500 : ms;
        uint32_t start = DWT->CYCCNT;
        while (!elapsed_ms(start, interval)) __NOP();
        ms -= interval;
    }
}

static void gpio_mode(GPIO_TypeDef *port, unsigned pin, unsigned mode)
{
    port->MODER = (port->MODER & ~(3UL << (pin * 2))) | (mode << (pin * 2));
    port->OTYPER &= ~(1UL << pin);
    port->PUPDR &= ~(3UL << (pin * 2));
    port->OSPEEDR = (port->OSPEEDR & ~(3UL << (pin * 2))) | (1UL << (pin * 2));
}

void board_init(void)
{
    g_board_stage = 1;
    /* ST SystemInit leaves HSI selected. Explicitly retain 16 MHz / APB1=APB2=16 MHz. */
    RCC->CR |= RCC_CR_HSION;
    while (!(RCC->CR & RCC_CR_HSIRDY)) {}
    RCC->CFGR &= ~(RCC_CFGR_SW | RCC_CFGR_HPRE | RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2);
    while ((RCC->CFGR & RCC_CFGR_SWS) != 0) {}
    SystemCoreClockUpdate();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    /* Explicit Flash vector location also supports startup via a bootloader. */
    SCB->VTOR = FLASH_BASE;
    __DSB();
    __ISB();
    SysTick_Config(SystemCoreClock / 1000UL);
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_GPIOBEN |
                    RCC_AHB1ENR_GPIOFEN | RCC_AHB1ENR_GPIOGEN;
    (void)RCC->AHB1ENR;
    /* Preload idle levels BEFORE enabling output drivers.
       PB14: onboard Flash CS, PG7: FPGA CS; both must start inactive.
       PG7: FPGA CS; PG6 kept low (NRF CE). Remove any NRF module from U16. */
    GPIOB->BSRR = 1UL << 14;
    GPIOG->BSRR = (1UL << (6 + 16)) | (1UL << 7);
    GPIOF->BSRR = (1UL << 9) | (1UL << 10);
    gpio_mode(GPIOB, 14, 1);
    gpio_mode(GPIOG, 6, 1);
    gpio_mode(GPIOG, 7, 1);
    gpio_mode(GPIOF, 9, 1);
    gpio_mode(GPIOF, 10, 1);
    g_board_stage = 2;

    /* SPI1 AF5 PB3=SCK, PB4=MISO, PB5=MOSI. SWD remains on PA13/14.
       Disable SWO trace on PB3; use SWD, not full JTAG. */
    DBGMCU->CR &= ~DBGMCU_CR_TRACE_IOEN;
    gpio_mode(GPIOB, 3, 2);
    gpio_mode(GPIOB, 4, 2);
    gpio_mode(GPIOB, 5, 2);
    GPIOB->AFR[0] = (GPIOB->AFR[0] & ~((15UL << 12) | (15UL << 16) | (15UL << 20))) |
                    (5UL << 12) | (5UL << 16) | (5UL << 20);
    /* No extra pull-down: TXS0108E includes internal pull-ups. */
    RCC->APB2ENR |= RCC_APB2ENR_SPI1EN | RCC_APB2ENR_USART1EN;
    RCC->APB2RSTR |= RCC_APB2RSTR_SPI1RST;
    RCC->APB2RSTR &= ~RCC_APB2RSTR_SPI1RST;
    /* CPOL=0, CPHA=0, 8-bit, MSB-first, software NSS. 16MHz/128=125kHz. */
    SPI1->CR1 = SPI_CR1_MSTR | SPI_CR1_SSM | SPI_CR1_SSI |
                SPI_CR1_BR_2 | SPI_CR1_BR_1;
    SPI1->CR2 = 0;
    SPI1->CR1 |= SPI_CR1_SPE;
    g_board_stage = 3;

    /* USART1 PA9 TX, PA10 RX, AF7. P10 jumpers route to onboard CH340C. */
    gpio_mode(GPIOA, 9, 2);
    gpio_mode(GPIOA, 10, 2);
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~((15UL << 4) | (15UL << 8))) |
                    (7UL << 4) | (7UL << 8);
    USART1->CR1 = 0;
    USART1->CR2 = 0;
    USART1->CR3 = 0;
    USART1->BRR = 139; /* 16 MHz / 115200, oversampling 16. */
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
    g_board_stage = 4;
}

void board_startup_indication(void)
{
    unsigned i;
    for (i = 0; i < 3; ++i) {
        GPIOF->BSRR = (1UL << 25) | (1UL << 26); /* Both LEDs on, active low. */
        board_delay_ms(150);
        GPIOF->BSRR = (1UL << 9) | (1UL << 10);
        board_delay_ms(150);
    }
    g_board_stage = 5;
}

void board_puts(const char *text)
{
    while (*text) {
        uint32_t start = DWT->CYCCNT;
        while (!(USART1->SR & USART_SR_TXE)) {
            if (elapsed_ms(start, 20)) { ++g_uart_timeouts; return; }
        }
        USART1->DR = (uint8_t)*text++;
    }
}

void board_hex8(uint8_t value)
{
    const char digits[] = "0123456789ABCDEF";
    char text[3];
    text[0] = digits[value >> 4]; text[1] = digits[value & 15]; text[2] = 0;
    board_puts(text);
}

void board_led_result(int success)
{
    /* Red = main-loop heartbeat, even without FPGA. Green = last cycle passed. */
    GPIOF->BSRR = (GPIOF->ODR & (1UL << 9)) ? (1UL << 25) : (1UL << 9);
    GPIOF->BSRR = success ? (1UL << 26) : (1UL << 10);
}

static int wait_flag(uint32_t mask, int set)
{
    uint32_t start = DWT->CYCCNT;
    while (((SPI1->SR & mask) != 0) != set) {
        if (elapsed_ms(start, 20)) return -1;
    }
    return 0;
}

static int hardware_frame(const uint8_t tx[4], uint8_t rx[4])
{
    unsigned i;
    volatile uint32_t discard;
    /* Frame boundary requires CS high. Gaps deliberately generous for initial bring-up. */
    GPIOG->BSRR = 1UL << 7;
    board_delay_ms(1);
    for (i=0; i<8 && (SPI1->SR & SPI_SR_RXNE); ++i) discard=SPI1->DR;
    if (SPI1->SR & SPI_SR_RXNE) goto fail;
    discard = SPI1->SR;
    (void)discard;
    GPIOG->BSRR = 1UL << (7 + 16);
    board_delay_ms(1);
    for (i = 0; i < 4; ++i) {
        if (wait_flag(SPI_SR_TXE, 1)) goto fail;
        *(__IO uint8_t *)&SPI1->DR = tx[i];
        if (wait_flag(SPI_SR_RXNE, 1)) goto fail;
        rx[i] = *(__IO uint8_t *)&SPI1->DR;
    }
    if (wait_flag(SPI_SR_BSY, 0)) goto fail;
    board_delay_ms(1);
    GPIOG->BSRR = 1UL << 7;
    return 0;
fail:
    GPIOG->BSRR = 1UL << 7;
    /* Abort the partial FPGA transaction, then recover the SPI peripheral. */
    SPI1->CR1 &= ~SPI_CR1_SPE;
    discard = SPI1->DR;
    discard = SPI1->SR;
    SPI1->CR1 |= SPI_CR1_SPE;
    return -1;
}

int board_select_backend(unsigned hardware)
{
    GPIOG->BSRR=1UL<<7;
    SPI1->CR1 &= ~SPI_CR1_SPE;
    GPIOB->BSRR=(1UL<<19)|(1UL<<21);
    if(hardware){
        if(SystemCoreClock!=16000000UL || (RCC->CFGR & (RCC_CFGR_SWS|RCC_CFGR_HPRE|RCC_CFGR_PPRE1|RCC_CFGR_PPRE2)))return -1;
        RCC->APB2RSTR|=RCC_APB2RSTR_SPI1RST;RCC->APB2RSTR&=~RCC_APB2RSTR_SPI1RST;
        gpio_mode(GPIOB,3,2);gpio_mode(GPIOB,4,2);gpio_mode(GPIOB,5,2);
        GPIOB->AFR[0]=(GPIOB->AFR[0]&~((15UL<<12)|(15UL<<16)|(15UL<<20)))|(5UL<<12)|(5UL<<16)|(5UL<<20);
        SPI1->CR1=SPI_CR1_MSTR|SPI_CR1_SSM|SPI_CR1_SSI|SPI_CR1_BR_2|SPI_CR1_BR_1;
        SPI1->CR2=0;SPI1->CR1|=SPI_CR1_SPE;
        if(SPI1->CR1!=(SPI_CR1_SPE|SPI_CR1_MSTR|SPI_CR1_SSM|SPI_CR1_SSI|SPI_CR1_BR_2|SPI_CR1_BR_1))return -1;
    }else{gpio_mode(GPIOB,3,1);gpio_mode(GPIOB,4,0);gpio_mode(GPIOB,5,1);}
    hardware_backend=hardware;board_delay_ms(1);return 0;
}

int board_spi_frame(const uint8_t tx[4],uint8_t rx[4])
{
    unsigned i,j;
    for(i=0;i<4;++i)rx[i]=0;
    if(hardware_backend)return hardware_frame(tx,rx);
    /* Slow Mode0: 1ms high/2ms low nominal, same direct BSRR writes as V5. */
    GPIOG->BSRR=1UL<<7;GPIOB->BSRR=1UL<<19;board_delay_ms(1);
    GPIOG->BSRR=1UL<<23;board_delay_ms(1);
    for(i=0;i<4;++i)for(j=0;j<8;++j){
        GPIOB->BSRR=(tx[i]&(0x80U>>j))?(1UL<<5):(1UL<<21);board_delay_ms(1);
        GPIOB->BSRR=1UL<<3;board_delay_ms(1);
        rx[i]=(uint8_t)((rx[i]<<1)|((GPIOB->IDR>>4)&1U));
        GPIOB->BSRR=1UL<<19;board_delay_ms(1);
    }
    board_delay_ms(1);GPIOG->BSRR=1UL<<7;board_delay_ms(1);return 0;
}

uint32_t board_millis(void) { return ticks; }
