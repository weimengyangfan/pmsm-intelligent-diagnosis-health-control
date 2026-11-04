#include "demo.h"
#include "board.h"
#include <stdint.h>

/* Same 4-byte, next-CS response protocol as the real-board accepted baseline.
   Always use a valid PING for FETCH; never a dummy all-zero command. */
static unsigned mode,step,backend_ready;
static uint32_t last_step;

static int fail(const char *reason)
{
    mode=0;
    board_puts("FAIL: "); board_puts(reason);
    board_puts("; animation stopped\r\n");
    board_led_result(0);
    return -1;
}

static int valid(const uint8_t r[4])
{
    return r[0]==0x5A && r[3]==(uint8_t)(r[0]^r[1]^r[2]);
}

static void hexframe(const uint8_t a[4])
{
    unsigned i;
    for(i=0;i<4;++i)board_hex8(a[i]);
}

static int command(uint8_t cmd,uint8_t value,uint8_t *reply)
{
    uint8_t tx[4]={0xA5,0,0,0},rq[4]={0},ft[4]={0};
    const uint8_t fetch[4]={0xA5,1,0,0xA4};
    if(!backend_ready)return fail("SPI configuration");
    tx[1]=cmd;tx[2]=value;tx[3]=(uint8_t)(0xA5^cmd^value);
    if(board_spi_frame(tx,rq)||board_spi_frame(fetch,ft))return fail("SPI timeout");
    if(!valid(rq)||!valid(ft)) {
        board_puts("REQUEST_RX=");hexframe(rq);board_puts(" FETCH_RX=");hexframe(ft);board_puts("\r\n");
        return fail("frame header/XOR");
    }
    /* REQUEST_RX is the preceding command's reply; only FETCH belongs to cmd. */
    if(ft[1]) {board_puts("STATUS=");board_hex8(ft[1]);board_puts("\r\n");return fail("FPGA status");}
    *reply=ft[2];
    return 0;
}

static int set_leds(uint8_t value)
{
    uint8_t ack,readback;
    int i;
    if(command(0x10,value,&ack)||command(0x11,0,&readback))return -1;
    if(ack!=value||readback!=value)return fail("LED write/readback mismatch");
    board_puts("LED=0x");board_hex8(value);board_puts(" BITS=");
    for(i=3;i>=0;--i)board_puts((value&(1U<<i))?"1":"0");
    board_puts(" WRITE_ACK=");board_hex8(ack);board_puts(" READBACK=");board_hex8(readback);
    board_puts(" OK\r\n");board_led_result(1);
    return 0;
}


/* Low-rate feature transport over the existing 4-bit state register.
   Each nibble is a distinct acknowledged SPI write, held for 100 ms.
   Linux detects new writes via its coherent write_count/status snapshot. */
static uint16_t feature_sequence;
static uint16_t feature_crc(const uint8_t *data, unsigned length)
{
    uint16_t crc=0xFFFFU;
    unsigned i,j;
    for(i=0;i<length;++i) {
        crc=(uint16_t)(crc^((uint16_t)data[i]<<8));
        for(j=0;j<8;++j)
            crc=(uint16_t)((crc<<1)^((crc&0x8000U)?0x1021U:0U));
    }
    return crc;
}
static void feature_u32(uint8_t *p, uint32_t word)
{
    unsigned i;
    for(i=0;i<4;++i)p[i]=(uint8_t)(word>>(8U*i));
}
static int feature_transmit(const uint8_t packet[16]);
static int feature_send(uint32_t b_bits, uint32_t c_bits, uint8_t standardized)
{
    uint8_t packet[16];
    uint16_t crc;
    mode=0;
    ++feature_sequence;
    packet[0]=0xA5;packet[1]=0x5A;packet[2]=1;packet[3]=standardized;
    packet[4]=(uint8_t)feature_sequence;packet[5]=(uint8_t)(feature_sequence>>8);
    feature_u32(packet+6,b_bits);feature_u32(packet+10,c_bits);
    crc=feature_crc(packet,14);
    packet[14]=(uint8_t)crc;packet[15]=(uint8_t)(crc>>8);
    return feature_transmit(packet);
}

static int feature_transmit(const uint8_t packet[16])
{
    unsigned i;
    uint8_t value,ack;
    mode=0;
    board_puts("FEATURE_TX_BEGIN seq=0x");
    board_hex8(packet[5]);board_hex8(packet[4]);board_puts(" packet=");
    for(i=0;i<16;++i)board_hex8(packet[i]);
    board_puts("\r\n");
    for(i=0;i<32;++i) {
        value=(uint8_t)((i&1U)?(packet[i/2U]&15U):(packet[i/2U]>>4));
        if(command(0x10,value,&ack))return -1;
        if(ack!=value)return fail("feature nibble ACK mismatch");
        board_delay_ms(100);
    }
    board_puts("FEATURE_TX_SPI_ACK_OK: 32 nibbles; verify Linux CRC/NPU output\r\n");
    return 0;
}

#include "motor_raw.h"

static void help(void)
{
    board_puts("\r\nMOTOR MONITOR V1 | SPI1 125kHz Mode0 | UART 115200 8N1\r\n"
      "0..9 / A..F : set 4-bit LED pattern (uppercase A-F)\r\n"
      "l : running light, n : binary counter, k : blink all (500ms steps)\r\n"
      "s : stop and hold, r : read LEDs, p : PING, v : version\r\n"
      "t : run original SW + HW100 acceptance, h/? : help\r\n"
      "x : send saved standardized Normal sample (start Linux receiver first)\r\n"
      "y : send synthetic raw B=+0.5A,C=0A; z : raw B=0A,C=-0.5A\r\n"
      "bit0=D18 bit1=D20 bit2=D19 bit3=D21; 1=ON\r\n"
      "RAW_HOST V1: cycle replay / trapezoidal mean on F4\r\nHOST: @32hex+LF; !32hex+LF for CRC rejection test\r\nREADY: try p, 1, 2, 4, 8, F, 0, l, s\r\n");
}

void demo_init(void)
{
    mode=0;step=0;last_step=board_millis();
    backend_ready=board_select_backend(1)==0;
    help();
    if(!backend_ready)fail("SPI configuration");
}

/* @ + 32 hexadecimal digits + LF: validated packet.
   ! uses the same format but deliberately permits a bad packet CRC for testing. */
static unsigned host_active,host_count;
static char host_hex[32];
static int digit(unsigned char c) {
    if(c>='0'&&c<='9')return c-'0';
    if(c>='a'&&c<='f')return c-'a'+10;
    if(c>='A'&&c<='F')return c-'A'+10;
    return -1;
}
static int host_input(unsigned char c) {
    uint8_t p[16];unsigned i;uint16_t crc;
    if(c=='@'||c=='!'){host_active=c;host_count=0;return 1;}
    if(!host_active)return 0;
    if(c=='\r')return 1;
    if(c=='\n') {
        if(host_count!=32){host_active=0;board_puts("HOST_REJECT length\r\n");return 1;}
        for(i=0;i<16;++i)p[i]=(uint8_t)((digit(host_hex[2*i])<<4)|digit(host_hex[2*i+1]));
        crc=feature_crc(p,14);
        if(p[0]!=0xA5||p[1]!=0x5A||p[2]!=1||p[3]>1||
           (host_active=='@'&&((uint8_t)crc!=p[14]||(uint8_t)(crc>>8)!=p[15]))) {
            host_active=0;board_puts("HOST_REJECT header/CRC\r\n");return 1;
        }
        host_active=0;feature_transmit(p);return 1;
    }
    if(host_count>=32||digit(c)<0){host_active=0;board_puts("HOST_REJECT hex\r\n");return 1;}
    host_hex[host_count++]=(char)c;return 1;
}

void demo_input(unsigned char ch)
{
    uint8_t data;
    unsigned new_mode=0;
    if(raw_input(ch))return;
    if(host_input(ch))return;
    if(ch=='\r'||ch=='\n'||ch==' '||ch=='\t')return;
    if((ch>='0'&&ch<='9')||(ch>='A'&&ch<='F')) {
        mode=0;
        set_leds((uint8_t)(ch<='9'?ch-'0':ch-'A'+10));
        return;
    }
    if(ch=='x') {feature_send(0x3899E6C5UL,0x3752E950UL,1);return;}
    if(ch=='y') {feature_send(0x3F000000UL,0x00000000UL,0);return;}
    if(ch=='z') {feature_send(0x00000000UL,0xBF000000UL,0);return;}
    if(ch=='l')new_mode=1;
    else if(ch=='n')new_mode=2;
    else if(ch=='k')new_mode=3;
    if(new_mode) {
        mode=new_mode;step=0;last_step=board_millis()-500U;
        board_puts(mode==1?"RUNNING_LIGHT\r\n":mode==2?"BINARY_COUNTER\r\n":"BLINK_ALL\r\n");
        return;
    }
    if(ch=='s') {mode=0;board_puts("STOP: holding current pattern\r\n");}
    else if(ch=='r') {
        if(!command(0x11,0,&data)) {
            if(data>15)fail("readback outside 4-bit range");
            else {board_puts("READBACK=0x");board_hex8(data);board_puts(" OK\r\n");}
        }
    } else if(ch=='p') {
        if(!command(1,0,&data)) {if(data==0xC3){board_puts("PING_PASS RX=5A00C399\r\n");board_led_result(1);}else fail("PING data");}
    } else if(ch=='v') {
        if(!command(0x20,0,&data)) {board_puts("FPGA_VERSION=0x");board_hex8(data);board_puts("\r\n");}
    } else if(ch=='h'||ch=='?')help();
    else board_puts("UNKNOWN COMMAND: send h (LED hex A-F must be uppercase)\r\n");
}

void demo_poll(void)
{
    uint8_t value;
    uint32_t now=board_millis();
    if(!mode || (uint32_t)(now-last_step)<500U)return;
    last_step=now;
    if(mode==1)value=(uint8_t)(1U<<(step&3U));
    else if(mode==2)value=(uint8_t)(step&15U);
    else value=(step&1U)?0:15;
    if(!set_leds(value))++step;
}
