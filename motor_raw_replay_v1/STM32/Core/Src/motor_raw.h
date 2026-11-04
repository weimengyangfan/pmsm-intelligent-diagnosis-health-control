/* Included by demo.c: reuses the accepted SPI transport, no new board pins. */
#include <string.h>
static unsigned raw_active,raw_count,raw_expected,raw_ready,raw_line_active,raw_length;
static uint16_t raw_seq,raw_crc,raw_expected_crc;
static double raw_prev_t,raw_prev_b,raw_prev_c,raw_area_b,raw_area_c;
static uint32_t raw_b_bits,raw_c_bits;
static char raw_line[40];
static void raw_hex16(uint16_t n){board_hex8((uint8_t)(n>>8));board_hex8((uint8_t)n);}
static void raw_hex32(uint32_t n){raw_hex16((uint16_t)(n>>16));raw_hex16((uint16_t)n);}
static int raw_digit(char c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;return -1;}
static uint32_t raw_word(const char *p,unsigned n){uint32_t v=0;unsigned i;for(i=0;i<n;++i)v=(v<<4)|(unsigned)raw_digit(p[i]);return v;}
static uint16_t raw_crc_more(uint16_t crc,const uint8_t *p,unsigned n){unsigned i,j;for(i=0;i<n;++i){crc^=(uint16_t)p[i]<<8;for(j=0;j<8;++j)crc=(uint16_t)((crc<<1)^((crc&0x8000U)?0x1021U:0U));}return crc;}
static void raw_error(const char *s){raw_active=0;raw_ready=0;board_puts("RAW_ERROR ");board_puts(s);board_puts("\r\n");}
static void raw_process(void){
 unsigned i,index;uint32_t bits[3];float values[3];uint8_t bytes[14],packet[16];uint16_t crc;double dt;float mean;
 if(raw_line[0]=='X'&&raw_length==1){raw_active=raw_ready=0;board_puts("RAW_ABORTED\r\n");return;}
 for(i=1;i<raw_length;++i)if(raw_digit(raw_line[i])<0){raw_error("hex");return;}
 if(raw_line[0]=='B'&&raw_length==13){
  raw_active=raw_ready=0;raw_seq=(uint16_t)raw_word(raw_line+1,4);raw_expected=(unsigned)raw_word(raw_line+5,4);raw_expected_crc=(uint16_t)raw_word(raw_line+9,4);
  if(raw_expected<3||raw_expected>4096){raw_error("point_count");return;}
  raw_count=0;raw_crc=0xffff;raw_area_b=raw_area_c=0;raw_active=1;mode=0;
  board_puts("RAW_BEGIN seq=");raw_hex16(raw_seq);board_puts("\r\n");return;
 }
 if(raw_line[0]=='D'&&raw_length==29){
  index=(unsigned)raw_word(raw_line+1,4);
  if(!raw_active||index!=raw_count||raw_count>=raw_expected){raw_error("order/count");return;}
  bytes[0]=(uint8_t)index;bytes[1]=(uint8_t)(index>>8);
  for(i=0;i<3;++i){bits[i]=raw_word(raw_line+5+8*i,8);if((bits[i]&0x7f800000U)==0x7f800000U){raw_error("nonfinite");return;}memcpy(&values[i],&bits[i],4);feature_u32(bytes+2+4*i,bits[i]);}
  if(values[0]<0||values[0]>1||values[1]>1000||values[1]<-1000||values[2]>1000||values[2]<-1000){raw_error("range");return;}
  if(raw_count==0){if(values[0]!=0){raw_error("first_time");return;}}
  else {dt=(double)values[0]-raw_prev_t;if(dt<=0){raw_error("time_order");return;}raw_area_b+=.5*(raw_prev_b+(double)values[1])*dt;raw_area_c+=.5*(raw_prev_c+(double)values[2])*dt;}
  raw_prev_t=values[0];raw_prev_b=values[1];raw_prev_c=values[2];raw_crc=raw_crc_more(raw_crc,bytes,14);++raw_count;
  board_puts("RAW_ACK seq=");raw_hex16(raw_seq);board_puts(" index=");raw_hex16((uint16_t)index);board_puts("\r\n");return;
 }
 if(raw_line[0]=='E'&&raw_length==5){
  if(!raw_active||raw_word(raw_line+1,4)!=raw_seq||raw_count!=raw_expected||raw_crc!=raw_expected_crc){raw_error("raw_CRC/count/seq");return;}
  if(raw_prev_t<=0||raw_prev_t>.100001){raw_error("frequency_below_10Hz");return;}
  mean=(float)(raw_area_b/raw_prev_t);memcpy(&raw_b_bits,&mean,4);mean=(float)(raw_area_c/raw_prev_t);memcpy(&raw_c_bits,&mean,4);raw_active=0;raw_ready=1;
  board_puts("RAW_RESULT seq=");raw_hex16(raw_seq);board_puts(" b=");raw_hex32(raw_b_bits);board_puts(" c=");raw_hex32(raw_c_bits);board_puts(" points=");raw_hex16((uint16_t)raw_count);board_puts("\r\n");return;
 }
 if(raw_line[0]=='T'&&raw_length==5){
  if(!raw_ready||raw_word(raw_line+1,4)!=raw_seq){raw_error("not_prepared");return;}raw_ready=0;
  packet[0]=0xa5;packet[1]=0x5a;packet[2]=1;packet[3]=0;packet[4]=(uint8_t)raw_seq;packet[5]=(uint8_t)(raw_seq>>8);
  feature_u32(packet+6,raw_b_bits);feature_u32(packet+10,raw_c_bits);crc=feature_crc(packet,14);packet[14]=(uint8_t)crc;packet[15]=(uint8_t)(crc>>8);feature_transmit(packet);return;
 }
 raw_error("command");
}
static int raw_input(unsigned char c){
 if(c=='~'){raw_line_active=1;raw_length=0;return 1;}
 if(!raw_line_active)return 0;
 if(c=='\r')return 1;
 if(c=='\n'){raw_line_active=0;if(!raw_length)raw_error("empty");else raw_process();return 1;}
 if(raw_length>=sizeof(raw_line)){raw_line_active=0;raw_error("line_length");return 1;}
 raw_line[raw_length++]=(char)c;return 1;
}
