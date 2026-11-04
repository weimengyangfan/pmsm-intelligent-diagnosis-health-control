# 运行环境与实验复现

## 环境和分工

- 现场MATLAB记录为R2020b Update 8。需Simulink及电机模型所用工具箱。
- F4使用STM32F407，Keil项目记录ARM Compiler 5.06 update 7、Keil.STM32F4xx_DFP 3.1.1。
- FPGA平台为FMQL30TAI悟净Lite，使用厂商适配的Vivado 2018.3 / Procise及NPU工程。
- 板载ARM Linux通过厂商ICraft运行库调用ZG330。历史工具链记录ICraft 3.36.1，模型目标为@zhuget(330)，不能用早期Buyi目标替代。
- PC串口桥接依赖pyserial、paramiko。密码在运行时交互输入，不写入仓库。

## 模型与固件版本对应

R4现场准备模型的SHA256为5b36dd8e8b8312199cf10120ca5481f751770df2da1527e1c831f8d22c661bf8；现场settings所指原始SLX的SHA256为7c65b615e9eb24bc34f3424852a9e935db10f2bf50b1888cf587081de8c261d2。本次回收到的原始SLX哈希与后者不同。因此仓库不附带一个可假称直接复用旧验收的settings.json；使用当前模型时，应重新prepare、check并生成新的记录。数据字典与SLX同目录。

原始点固件源码位于motor_raw_replay_v1/STM32。它支持RAW_HOST V1。额外回收的特征通信现场HEX不含该协议，故不作为本仓库的R4最终固件发布；现场最终HEX/AXF仍需从成功运行的工程归档。无板卡软件测试不证明现场固件一致性。

厂商完整实现的runme.log记录post-route WNS=-0.623 ns、TNS=-22.224 ns及时序未满足告警，并缺少implementation_place_pre.tcl和implementation_place_post.tcl。公开模块并不因此取得整机时序通过结论。应由原厂环境补齐脚本、取得完整报告后处理具体路径，不能用空脚本或删除检查绕过。

## 训练与部署

models/training_export为基于上传MATLAB历史恢复的训练/导出脚本。它们保留分组划分和训练集标准化规则；恢复工作未重新训练或上板。models/saved保存已有训练MAT和image ONNX。尚需补成功logits ONNX及ICraft完整parse/quantize/compile配置、标定清单和日志，才能完整核对编译流程。

board内的motor_bias_mlp17_logits_ZG.json和.raw来自本次现场回收，SHA256与归档一致。服务运行依赖原NPU工具环境；不使用本地假分类代替实板结果。

## 实验和时间口径

2026-11-03保存记录由电机模型与实际STM32/FPGA/ARM/NPU联合产生，等待板卡期间模型时间暂停。反馈更新的是模型未来参考；本轮不是实际电机功率级执行的实时控制验收。

NPU推理及读取中位数0.576 ms与原始点上传至返回中位数6.069 s属于不同测量区间。参考斜坡0.25 s及后续响应使用模型时间。分类范围是正常及B/C预设偏移档位，不能从该结果泛化成所有电机故障的准确率。

## 独立复核

运行 `python verification/verify_saved_evidence.py`。程序直接读取保存的evidence.json.gz，核对原始点与源曲线、梯形积分与MCU均值、CRC和序号、三周期决策、动作因果顺序、动作前双组轨迹及动作后新诊断周期。它是保存资料的离线一致性复核，不构成新的硬件实验。
