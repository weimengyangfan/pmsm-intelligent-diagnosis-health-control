# Run after synthesis with synthesized/implemented design open.
foreach {label pin expected} {
    SPI U_motor_spi/board_clk 5.000
    GP U_motor_cdc/dst_clk 20.000
} {
    set p [get_pins -quiet $pin]
    if {![llength $p]} {error "Clock pin missing: $pin; open synthesized design first"}
    set clocks [get_clocks -quiet -of_objects $p]
    if {[llength $clocks]!=1} {error "Cannot identify single clock for $pin: $clocks"}
    set period [get_property PERIOD $clocks]
    puts "$label clock: $clocks, period $period ns"
    if {abs($period-$expected)>0.010} {error "$label clock differs from expected $expected ns; do not program"}
}
puts MOTOR_CLOCK_CHECK_PASS
# An older project-wide false_path can override a narrower max_delay.
# Refuse download if the new mailbox data constraint is ignored or fails.
set motor_holds [get_cells -hier -regexp {.*U_motor_cdc/hold_data_reg\[[0-9]+\]}]
set motor_dests [get_cells -hier -regexp {.*U_motor_cdc/dst_data_reg\[[0-9]+\]}]
set motor_paths [get_timing_paths -from $motor_holds -to $motor_dests -max_paths 1]
if {![llength $motor_paths]} {
    error "Mailbox data path is not timed (possible original clock-wide false_path). Send this output before programming."
}
set motor_requirement [get_property REQUIREMENT $motor_paths]
set motor_slack [get_property SLACK $motor_paths]
puts "Mailbox data requirement=$motor_requirement ns, slack=$motor_slack ns"
if {$motor_requirement>5.010 || $motor_slack<0} {
    error "Mailbox 5 ns bundled-data timing constraint is ignored or not met; do not program"
}
puts MOTOR_MAILBOX_TIMING_PASS
