# 文件来源与第三方依赖

本目录用于公开项目源代码及实验验证资料，尚未为整个项目另行选择统一开源许可证。公开可见不等同于对所有文件授予任意再许可权利。

- 自编部分：PC桥接、板端接收/确认策略、F4原始点协议与积分、FPGA SPI/快照模块、训练/导出脚本及离线审计程序。
- ARM CMSIS核心头文件保留在motor_raw_replay_v1/STM32/Drivers/CMSIS，许可见该目录LICENSE.txt。
- STMicroelectronics设备文件的来源与许可见motor_raw_replay_v1/STM32/THIRD_PARTY.md及Drivers/CMSIS/Device/ST/STM32F4xx/LICENSE.md。
- NPU硬件IP、运行库及编译器属于厂商平台依赖。本仓库提供自有网络的部署参数和调用代码，不提供厂商保密顶层、IP、EDIF、工具补丁或平台位流。
- 保存的测试集、模型、实拍图和实验记录来自用户提交的本项目材料；恢复脚本的原始批次和修改来源见models/training_export/PROVENANCE.json。
