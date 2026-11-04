#ifndef FPGA_BRIDGE_H
#define FPGA_BRIDGE_H
#include <stdint.h>
enum { FPGA_OK = 0, FPGA_IO_ERROR = -1, FPGA_FRAME_ERROR = -2,
       FPGA_STATUS_ERROR = -3, FPGA_DATA_ERROR = -4 };
typedef struct {
    uint8_t raw[4];
    uint8_t status;
    uint8_t data;
} fpga_reply_t;
/* Each call performs TWO separate CS transactions. Single caller only. */
int fpga_command(uint8_t command, uint8_t data, fpga_reply_t *reply);
#endif
