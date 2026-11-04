`timescale 1ns/1ps
// PING/version/4-bit state register on the hardware-proven onboard-clock architecture.
// Every state register uses the positive edge of board_clk; SPI is sampled data.
module spi_jfm_top (
    input wire sys_clk_p, input wire sys_clk_n,
    input wire spi_sck, input wire spi_mosi, input wire spi_cs_n,
    output wire spi_miso, input wire pl_key1, output wire [3:0] pl_led
);
    localparam [5:0] FILTER_LAST = 6'd63;
    localparam [31:0] INITIAL_REPLY = 32'h5A00005A;
    wire board_clk_ibuf, board_clk;
    IBUFDS #(.DIFF_TERM("FALSE"), .IBUF_LOW_PWR("FALSE")) clock_input (
        .I(sys_clk_p), .IB(sys_clk_n), .O(board_clk_ibuf));
    BUFG clock_global (.I(board_clk_ibuf), .O(board_clk));

    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [1:0] cs_sync=2'b11;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [1:0] sck_sync=2'b00;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [1:0] mosi_sync=2'b00;
    reg cs_filtered=1'b1, sck_filtered=1'b0, sck_previous=1'b0;
    reg [5:0] cs_count=6'd0, sck_count=6'd0;
    reg [26:0] heartbeat_count=27'd0;
    reg [31:0] rx_shift=32'd0;
    reg [5:0] rx_count=6'd0, tx_count=6'd0;
    reg [3:0] status_reg=4'h0; // configuration reset value; CS does NOT reset it
    reg [31:0] reply_pending=INITIAL_REPLY;
    // This word remains IMMUTABLE throughout each active CS transaction.
    // Only the falling-edge output index changes during the frame.
    reg [31:0] tx_snapshot=INITIAL_REPLY;
    wire sck_rising=!sck_previous && sck_filtered;
    wire sck_falling=sck_previous && !sck_filtered;
    wire [31:0] rx_complete={rx_shift[30:0],mosi_sync[1]};
    wire tx_bit=tx_count[5] ? 1'b0 : tx_snapshot[~tx_count[4:0]];

    function [31:0] ok_reply;
        input [7:0] value;
        begin ok_reply={8'h5A,8'h00,value,(8'h5A^value)}; end
    endfunction

    function [31:0] decode_request;
        input [31:0] frame;
        input [3:0] saved_value;
        begin
            if(frame[31:24]!=8'hA5)
                decode_request=32'h5AE200B8;
            else if(frame[7:0]!=(frame[31:24]^frame[23:16]^frame[15:8]))
                decode_request=32'h5AE100BB;
            else case(frame[23:16])
                8'h01: decode_request=32'h5A00C399;
                8'h20: decode_request=32'h5A00015B;
                8'h10: decode_request=ok_reply({4'h0,frame[11:8]});
                8'h11: decode_request=ok_reply({4'h0,saved_value});
                default: decode_request=32'h5AE300B9;
            endcase
        end
    endfunction

    always @(posedge board_clk) begin
        cs_sync<={cs_sync[0],spi_cs_n};
        sck_sync<={sck_sync[0],spi_sck};
        mosi_sync<={mosi_sync[0],spi_mosi};
        heartbeat_count<=heartbeat_count+1'b1;
        if (cs_sync[1]==cs_filtered)
            cs_count<=6'd0;
        else if (cs_count==FILTER_LAST) begin
            cs_filtered<=cs_sync[1]; cs_count<=6'd0;
        end else cs_count<=cs_count+1'b1;
        if (sck_sync[1]==sck_filtered)
            sck_count<=6'd0;
        else if (sck_count==FILTER_LAST) begin
            sck_filtered<=sck_sync[1]; sck_count<=6'd0;
        end else sck_count<=sck_count+1'b1;
        sck_previous<=sck_filtered;

        if (cs_filtered) begin
            // Synchronous idle preparation; no CS edge clocks or async resets.
            tx_snapshot<=reply_pending;
            tx_count<=6'd0;
            rx_shift<=32'd0;
            rx_count<=6'd0;
        end else begin
            if (sck_rising && rx_count<6'd32) begin
                rx_shift<=rx_complete;
                rx_count<=rx_count+1'b1;
                if (rx_count==6'd31) begin
                    // Complete exactly32 input bits; commit only a valid write.
                    // Pending reply and stored register never overwrite snapshot.
                    reply_pending<=decode_request(rx_complete,status_reg);
                    if(rx_complete[31:24]==8'hA5 &&
                       rx_complete[7:0]==(rx_complete[31:24]^rx_complete[23:16]^rx_complete[15:8]) &&
                       rx_complete[23:16]==8'h10)
                        status_reg<=rx_complete[11:8];
                end
            end
            if (sck_falling && tx_count<6'd32)
                tx_count<=tx_count+1'b1;
        end
    end

    // Same external idle-high gate as the proven fixed-output build.
    assign spi_miso=spi_cs_n ? 1'b1 : tx_bit;
    assign pl_led={(!cs_filtered && tx_bit),sck_filtered,cs_filtered,heartbeat_count[26]};
    // PL_KEY1 does not reset or gate the SPI protocol in this diagnostic stage.
endmodule
