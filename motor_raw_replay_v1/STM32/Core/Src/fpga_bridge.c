#include "fpga_bridge.h"
#include "board.h"

int fpga_command(uint8_t command, uint8_t data, fpga_reply_t *reply)
{
    uint8_t tx[4] = {0xA5, command, data, 0};
    uint8_t discarded[4];
    /* A valid PING clocks out the queued response, and queues another PING.
       The first response of each command is deliberately discarded. */
    const uint8_t fetch[4] = {0xA5, 0x01, 0x00, 0xA4};
    unsigned i;
    reply->status = 0xFF;
    reply->data = 0;
    for (i = 0; i < 4; ++i) reply->raw[i] = 0;
    tx[3] = (uint8_t)(tx[0] ^ tx[1] ^ tx[2]);
    if (board_spi_frame(tx, discarded) || board_spi_frame(fetch, reply->raw))
        return FPGA_IO_ERROR;
    if (reply->raw[0] != 0x5A ||
        reply->raw[3] != (uint8_t)(reply->raw[0] ^ reply->raw[1] ^ reply->raw[2]))
        return FPGA_FRAME_ERROR;
    reply->status = reply->raw[1];
    reply->data = reply->raw[2];
    return reply->status == 0 ? FPGA_OK : FPGA_STATUS_ERROR;
}
