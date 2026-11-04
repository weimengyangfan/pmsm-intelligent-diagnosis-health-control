#include "acceptance.h"
#include "board.h"
volatile acceptance_stats_t g_acceptance_sw,g_acceptance_hw;
volatile uint32_t g_slow_full_pass,g_hw_ran,g_acceptance_finished;
enum {OK=0,TIMEOUT=1,FRAME=2,STATUS=3,DATA=4,UNSUPPORTED=5};
static unsigned hw_mode,round_index;
static void number(uint32_t v){char buf[11];unsigned i=10;buf[10]=0;do{buf[--i]=(char)('0'+v%10U);v/=10U;}while(v);board_puts(buf+i);}
static void field(const char *n,uint32_t v){board_puts(n);number(v);}
static void hex4(const uint8_t a[4]){unsigned i;for(i=0;i<4;++i)board_hex8(a[i]);}
static void summary(const char *n,const volatile acceptance_stats_t *s){
 board_puts(n);field(" rounds=",s->rounds);field(" commands=",s->commands);field(" frames=",s->frames);field(" passed=",s->passed);
 field(" timeout=",s->timeouts);field(" header=",s->header_errors);field(" xor=",s->xor_errors);field(" status=",s->status_errors);
 field(" unsupported=",s->unsupported);field(" data=",s->data_errors);field(" readback_ok=",s->pairs_ok);
 field(" readback_mismatch=",s->pairs_mismatch);field(" readback_skipped=",s->pairs_skipped);board_puts("\r\n");
}
static int valid_frame(const uint8_t r[4],volatile acceptance_stats_t *s){int good=1;
 if(r[0]!=0x5A){++s->header_errors;good=0;}
 if(r[3]!=(uint8_t)(r[0]^r[1]^r[2])){++s->xor_errors;good=0;}return good;
}
static int command(volatile acceptance_stats_t *s,uint8_t cmd,uint8_t val,uint8_t expected){
 uint8_t tx[4]={0xA5,0,0,0},rq[4]={0},ft[4]={0};const uint8_t fetch[4]={0xA5,1,0,0xA4};
 int rc=OK,a,b;tx[1]=cmd;tx[2]=val;tx[3]=(uint8_t)(tx[0]^cmd^val);++s->commands;++s->frames;
 if(board_spi_frame(tx,rq)){++s->timeouts;rc=TIMEOUT;}else{
  ++s->frames;if(board_spi_frame(fetch,ft)){++s->timeouts;rc=TIMEOUT;}else{
   a=valid_frame(rq,s);b=valid_frame(ft,s);
   if(!a||!b)rc=FRAME;else if(ft[1]!=0){++s->status_errors;if(ft[1]==0xE3){++s->unsupported;rc=UNSUPPORTED;}else rc=STATUS;}
   else if(ft[2]!=expected){++s->data_errors;rc=DATA;}
  }
 }
 if(rc==OK)++s->passed;
 if(!hw_mode||round_index==0||rc!=OK){
  board_puts(hw_mode?"HW":"SW");board_puts(" CMD=");board_hex8(cmd);board_puts(" TX=");hex4(tx);
  board_puts(" REQUEST_RX=");hex4(rq);board_puts(" FETCH_RX=");hex4(ft);board_puts(" EXPECT_DATA=");board_hex8(expected);
  board_puts(rc==OK?" OK\r\n":rc==UNSUPPORTED?" UNSUPPORTED_E3\r\n":rc==TIMEOUT?" TIMEOUT\r\n":rc==FRAME?" FRAME_ERROR\r\n":rc==STATUS?" STATUS_ERROR\r\n":" DATA_ERROR\r\n");
 }return rc;
}
static void suite(volatile acceptance_stats_t *s){unsigned v;int w,r;++s->rounds;
 if(command(s,1,0,0xC3)!=OK){board_puts("SUITE_ABORT: PING did not pass\r\n");return;}
 command(s,0x20,0,1);
 for(v=0;v<16;++v){w=command(s,0x10,(uint8_t)v,(uint8_t)v);r=command(s,0x11,0,(uint8_t)v);
  if(w==OK&&r==OK)++s->pairs_ok;else if(w==DATA||r==DATA)++s->pairs_mismatch;else ++s->pairs_skipped;}
}
static int clean(const volatile acceptance_stats_t *s){
 return s->commands==34&&s->passed==34&&s->pairs_ok==16&&!s->timeouts&&!s->header_errors&&!s->xor_errors&&
 !s->status_errors&&!s->data_errors&&!s->unsupported&&!s->pairs_mismatch&&!s->pairs_skipped;
}
void acceptance_run(void){acceptance_stats_t z={0};unsigned r;
 g_acceptance_sw=z;g_acceptance_hw=z;g_slow_full_pass=0;g_hw_ran=0;g_acceptance_finished=0;hw_mode=0;round_index=0;
 board_puts("ACCEPTANCE_BEGIN SW slow Mode0 1ms phases; unchanged pins\r\n");
 if(board_select_backend(0)){board_puts("SW_CONFIG_ERROR\r\n");g_acceptance_finished=1;return;}
 suite(&g_acceptance_sw);summary("SW_SUMMARY",&g_acceptance_sw);g_slow_full_pass=(uint32_t)clean(&g_acceptance_sw);
 if(!g_slow_full_pass){board_puts("SW_FULL_ACCEPTANCE_NOT_PASS\r\nHW_NOT_RUN rounds=0/100: slow full suite not passed; unsupported commands require FPGA implementation\r\n");
  g_acceptance_finished=1;board_led_result(0);return;}
 board_puts("SW_FULL_ACCEPTANCE_PASS\r\nTIMING_REVIEW: FPGA200MHz filter64 logic budget350ns; 125kHz half4000ns; external delay unmeasured\r\n");
 if(board_select_backend(1)){board_puts("HW_NOT_RUN: MCU clock/SPI config mismatch\r\n");board_select_backend(0);g_acceptance_finished=1;return;}
 hw_mode=1;g_hw_ran=1;board_puts("HW_BEGIN SPI1 Mode0 8bit MSB 125kHz rounds=100\r\n");
 for(r=0;r<100;++r){round_index=r;suite(&g_acceptance_hw);if((r+1)%10==0){field("HW_PROGRESS round=",r+1);board_puts("\r\n");}}
 summary("HW_SUMMARY",&g_acceptance_hw);
 board_puts(g_acceptance_hw.commands==3400&&g_acceptance_hw.passed==3400&&g_acceptance_hw.pairs_ok==1600?"HW_FULL_ACCEPTANCE_PASS\r\n":"HW_FULL_ACCEPTANCE_FAIL\r\n");
 board_select_backend(0);g_acceptance_finished=1;board_led_result(g_acceptance_hw.passed==3400);board_puts("ACCEPTANCE_END\r\n");
}
