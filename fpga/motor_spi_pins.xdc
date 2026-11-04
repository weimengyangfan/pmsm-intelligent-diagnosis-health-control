# Same pins as the 2026-10-20 accepted 125 kHz SPI build.
set_property PACKAGE_PIN AC21 [get_ports spi_sck]
set_property PACKAGE_PIN AC22 [get_ports spi_mosi]
set_property PACKAGE_PIN AE20 [get_ports spi_miso]
set_property PACKAGE_PIN AE21 [get_ports spi_cs_n]
set_property IOSTANDARD LVCMOS18 [get_ports {spi_sck spi_mosi spi_miso spi_cs_n}]
set_property PULLUP TRUE [get_ports spi_cs_n]
set_property PULLDOWN TRUE [get_ports {spi_sck spi_mosi}]
set_property DRIVE 4 [get_ports spi_miso]
set_property SLEW SLOW [get_ports spi_miso]
# External SPI signals are sampled data, never clocks.
set spi_first [get_cells -hier -regexp {.*U_motor_spi/(cs_sync|sck_sync|mosi_sync)_reg\[0\]}]
if {[llength $spi_first]!=3} {error "SPI first-stage synchronizers missing"}
set_false_path -from [get_ports {spi_sck spi_cs_n spi_mosi}] -to [get_pins -of_objects $spi_first -filter {REF_PIN_NAME == D}]
# Only first control synchronizer stages are asynchronous exceptions.
set cdc_first [get_cells -hier -regexp {.*U_motor_cdc/(req_sync|ack_sync)_reg\[0\]}]
if {[llength $cdc_first]!=2} {error "Mailbox first-stage synchronizers missing"}
set_false_path -to [get_pins -of_objects $cdc_first -filter {REF_PIN_NAME == D}]
# Bundled data is held until acknowledged; bound its flight time to 5 ns.
# gp_clk is 50 MHz in this official design, so this is shorter than one cycle.
set holds [get_cells -hier -regexp {.*U_motor_cdc/hold_data_reg\[[0-9]+\]}]
set dests [get_cells -hier -regexp {.*U_motor_cdc/dst_data_reg\[[0-9]+\]}]
if {![llength $holds] || ![llength $dests]} {error "Mailbox data registers missing"}
set_max_delay -datapath_only 5.000 -from $holds -to $dests
# MISO settles well before the next rising edge at 125 kHz (4 us half-cycle).
set txregs [get_cells -hier -regexp {.*U_motor_spi/(tx_snapshot|tx_count)_reg\[[0-9]+\]}]
set_max_delay -datapath_only 20.000 -from $txregs -to [get_ports spi_miso]
