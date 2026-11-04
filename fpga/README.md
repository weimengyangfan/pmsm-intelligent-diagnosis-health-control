# FPGA模块与厂商平台接入

公开模块为 `rtl/motor_spi_core.v` 和 `rtl/motor_snapshot_cdc.v`。接收SPI Mode 0、MSB first的4字节帧，请求为A5/CMD/DATA/XOR，下一CS事务回复5A/STATUS/DATA/XOR。

SPI接收由板载200 MHz时钟过采样，不把外部SCK当作全局逻辑时钟。完整有效帧才提交；保留状态、完整帧计数、有效写计数、错误计数和最近帧。CDC将4位状态与4个32位字段组成132位快照，请求/确认握手传递；它不是B/C两项FP32特征的原子数据包，也不是逐帧排队的FIFO。

ARM寄存器映射：基址0x400C0000，偏移0x84状态、0x88签名0x53504931、0x8C完整帧数、0x90有效写数、0x94错误数、0x98最近帧、0x9C版本。具体接入需在合法取得的厂商工程中连接本模块端口并实现该映射；板端脚本据此读取。

原厂 `ai7030_edif_top.v`、`adder_top.v` 等文件具有Confidential标记，公开目录不附带这些文件、PS_AI IP、厂商EDIF/工具补丁和实现产物。须使用与FMQL30TAI悟净Lite匹配的合法厂商工程和工具环境；本仓库不宣称仅凭这两个模块可重建整块NPU平台。

引脚参考见 motor_spi_pins.xdc：STM32 3.3 V与FPGA 1.8 V之间使用电平转换。硬件引脚和电源必须依据实际板卡版本核对。

有Icarus Verilog时可进行SPI/快照行为仿真：

```bash
iverilog -g2012 -s tb_motor_spi -o spi_test fpga/rtl/motor_spi_core.v fpga/rtl/motor_snapshot_cdc.v fpga/tests/proven_spi_reference.v fpga/tests/tb_motor_spi.v
vvp spi_test
```

公开版行为测试不替代Vivado时序、CDC约束及硬件验收。现存实现日志中的时序告警及缺失厂商钩子脚本见复现说明。
