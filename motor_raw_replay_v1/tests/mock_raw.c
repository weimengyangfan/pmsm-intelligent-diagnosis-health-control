#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "demo.h"
static uint8_t pending[4]={0x5A,0,0,0x5A};
static uint8_t payload[32];
static unsigned n;
static uint32_t ticks;
void board_init(void){}
void board_startup_indication(void){}
void board_delay_ms(uint32_t ms){ticks+=ms;}
uint32_t board_millis(void){return ticks;}
void board_led_result(int success){if(!success)abort();}
void board_puts(const char *s){fputs(s,stdout);}
void board_hex8(uint8_t v){printf("%02X",v);}
int board_select_backend(unsigned hw){(void)hw;return 0;}
int board_spi_frame(const uint8_t tx[4],uint8_t rx[4])
{
    unsigned i;
    for(i=0;i<4;++i)rx[i]=pending[i];
    if(tx[0]!=0xA5 || tx[3]!=(uint8_t)(tx[0]^tx[1]^tx[2]))abort();
    pending[0]=0x5A;pending[1]=0;
    if(tx[1]==0x10) {
        if(n>=32 || tx[2]>15)abort();
        payload[n++]=tx[2];pending[2]=tx[2];
    }else if(tx[1]==1)pending[2]=0xC3;
    else abort();
    pending[3]=(uint8_t)(pending[0]^pending[1]^pending[2]);
    return 0;
}
int main(void) {
 char line[128];unsigned i;
 demo_init();
 while(fgets(line,sizeof(line),stdin)) {
  n=0;ticks=0;
  for(i=0;line[i];++i)demo_input((unsigned char)line[i]);
  if(n==32){printf("TXPACKET ");for(i=0;i<32;i+=2)printf("%02x",(payload[i]<<4)|payload[i+1]);puts("");}
  
 }
 return 0;
}
