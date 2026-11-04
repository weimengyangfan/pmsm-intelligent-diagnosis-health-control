`timescale 1ns/1ps
// Continuously refreshed coherent mailbox, one request outstanding at a time.
// Init on FPGA configuration, like the proven SPI core. Runtime GP resets do
// not reset handshake phases; the official reg_ctrl retains its existing reset.
module motor_snapshot_cdc #(parameter WIDTH=132) (
    input wire src_clk, input wire dst_clk,
    input wire [WIDTH-1:0] src_data,
    output reg [WIDTH-1:0] dst_data={WIDTH{1'b0}}
);
    reg request=1'b0, acknowledge=1'b0;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [1:0] req_sync=2'b00;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [1:0] ack_sync=2'b00;
    (* KEEP="TRUE" *) reg [WIDTH-1:0] hold_data={WIDTH{1'b0}};
    always @(posedge src_clk) begin
        req_sync <= {req_sync[0],request};
        if (req_sync[1]!=acknowledge) begin
            hold_data <= src_data;
            acknowledge <= req_sync[1];
        end
    end
    always @(posedge dst_clk) begin
        ack_sync <= {ack_sync[0],acknowledge};
        if (ack_sync[1]==request) begin
            dst_data <= hold_data;
            request <= ~request;
        end
    end
endmodule
