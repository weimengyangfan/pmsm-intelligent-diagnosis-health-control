`timescale 1ns/1ps
module IBUFDS #(parameter DIFF_TERM="FALSE", IBUF_LOW_PWR="FALSE")
    (input I,IB, output O); assign O=I; endmodule
module BUFG(input I, output O); assign O=I; endmodule
module tb_motor_spi;
    reg clk=0, gp=0, gp_enable=1;
    always #2.5 clk=~clk;
    initial begin #3.7; forever begin #10; if(gp_enable) gp=~gp; end end
    reg cs=1,sck=0,mosi=0;
    wire miso, old_miso;
    wire [3:0] unused_led;
    wire [3:0] status;
    wire [31:0] frames,writes,errors,last;
    wire [131:0] snap;
    motor_spi_core dut(clk,sck,mosi,cs,miso,status,frames,writes,errors,last);
    spi_jfm_top ref_spi(clk,~clk,sck,mosi,cs,old_miso,1'b1,unused_led);
    motor_snapshot_cdc cdc(clk,gp,{last,errors,writes,frames,status},snap);
    reg [131:0] pending=0;
    integer captures=0;
    always @(posedge clk) begin
        if(cdc.req_sync[1]!=cdc.acknowledge) begin
            pending={last,errors,writes,frames,status};
            captures=captures+1;
        end
    end
    always @(posedge gp) begin
        if(cdc.ack_sync[1]==cdc.request) begin
            #0.2;
            if(snap!==pending) $fatal(1,"Torn mailbox snapshot");
        end
    end
    function [31:0] req;
        input [7:0] cmd,data;
        req={8'hA5,cmd,data,(8'hA5^cmd^data)};
    endfunction
    function [31:0] ok;
        input [7:0] data;
        ok={8'h5A,8'h00,data,(8'h5A^data)};
    endfunction
    integer transactions=0, expected_frames=0, expected_writes=0;
    task frame;
        input [31:0] tx;
        output [31:0] rx;
        integer b;
        begin
            rx=0; sck=0; cs=0; #4000;
            for(b=31;b>=0;b=b-1) begin
                mosi=tx[b]; #4000;
                sck=1; #2000;
                if(miso!==old_miso) $fatal(1,"SPI differs from accepted baseline");
                rx={rx[30:0],miso}; #2000;
                sck=0;
            end
            #4000; cs=1; #4000;
            expected_frames=expected_frames+1;
        end
    endtask
    reg [31:0] dummy,rx;
    task command;
        input [31:0] tx, expected;
        begin
            frame(tx,dummy);
            frame(req(8'h11,0),rx);
            if(rx!==expected) $fatal(1,"Reply mismatch tx=%h got=%h expected=%h",tx,rx,expected);
            transactions=transactions+1;
        end
    endtask
    task check_snapshot;
        input [3:0] expected;
        begin
            #3000;
            if(status!==expected || snap[3:0]!==expected) $fatal(1,"Status mismatch");
            if(frames!==expected_frames || snap[35:4]!==frames || snap[67:36]!==writes)
                $fatal(1,"Snapshot counters mismatch");
        end
    endtask
    integer r,i;
    initial begin
        #10000;
        // Short glitches must be rejected by 64-cycle filters.
        cs=0; sck=1; #100; cs=1; sck=0; #3000;
        if(frames!==0 || status!==0) $fatal(1,"Glitch accepted");
        for(r=0;r<3;r=r+1) begin
            command(req(8'h01,0),32'h5A00C399);
            command(req(8'h20,0),32'h5A00015B);
            for(i=0;i<16;i=i+1) begin
                command(req(8'h10,i),ok(i)); expected_writes=expected_writes+1;
                command(req(8'h11,0),ok(i));
                check_snapshot(i);
            end
        end
        if(writes!==expected_writes || errors!==0) $fatal(1,"Valid counters wrong");
        // Invalid requests cannot change saved status.
        command(32'hA51005FF,32'h5AE100BB);
        command(32'h00100010,32'h5AE200B8);
        command(req(8'hFF,0),32'h5AE300B9);
        check_snapshot(15);
        if(errors!==3 || snap[99:68]!==3) $fatal(1,"Error counter wrong");
        // Stop GP clock while SPI runs, then recover the mailbox.
        gp_enable=0; #200;
        command(req(8'h10,6),ok(6)); expected_writes=expected_writes+1;
        gp_enable=1; check_snapshot(6);
        // Incomplete transaction is discarded and does not commit state.
        cs=0; #4000;
        repeat(10) begin mosi=1; #4000; sck=1; #4000; sck=0; end
        #4000; cs=1; #4000; check_snapshot(6);
        if(writes!==expected_writes) $fatal(1,"Write counter wrong");
        $display("SPI_CDC_PASS commands=%0d complete_frames=%0d writes=%0d errors=%0d mailbox_captures=%0d",transactions,frames,writes,errors,captures);
        $finish;
    end
    initial begin #100000000; $fatal(1,"Simulation timeout"); end
endmodule
