# 永磁同步电机智能诊断与健康控制：AI 模型与 NPU 工程使用说明

本文说明本工程的模型、算子、NPU、板端服务和上位机的实际用法。文件名沿用 `llm_usage.md`；本工程使用的是 **17 类轻量 MLP 分类网络**，部署目标为 **ZG330 NPU**。

项目主页：[README.md](README.md)  
环境及版本对应：[docs/reproduction.md](docs/reproduction.md)  
第三方依赖：[THIRD_PARTY.md](THIRD_PARTY.md)

## 1. 先选择要运行的功能

| 目的 | 入口 | 需要什么 |
| --- | --- | --- |
| 查看程序和复核已有结果 | 第 4 节：离线检查 | 电脑、Python、仓库文件 |
| 检查 NPU 是否能运行现成模型 | 第 6 节：374 样本批测 | 悟净 Lite、已配置的 ZG330 平台及板端运行库 |
| 演示原始波形、特征、17 类诊断和 CRC 拦截 | 第 7 节：桌面诊断 | 电脑、STM32F407、FPGA/NPU、串口及网络 |
| 运行诊断驱动的模型反馈对照 | 第 8 节：R4 联动 | 上述硬件，加 MATLAB/Simulink 与模型初始化环境 |
| 更换数据集或重新训练部署 | 第 10 节：训练与导出 | MATLAB、训练数据、ONNX 支持、匹配的 ICraft 工具链 |

已有板端模型可以直接用于推理，**运行演示前不需要重新训练**。各入口涉及的接收服务应分别使用；切换时先退出上一入口。

## 2. 系统各部分做什么

| 部分 | 实际工作 |
| --- | --- |
| 电脑 / Simulink | 生成或读取电流与电角度数据，选择有效完整电周期；R4 中续算模型和更新未来转速参考 |
| STM32F407 | 接收原始 FP32 时间/B/C 电流点，按时间梯形积分求周期均值，封装特征包并通过 SPI 发送 |
| FPGA 逻辑 | SPI 完整帧接收、校验、状态/计数快照及跨时钟域交接，供 ARM 读取 |
| 板载 ARM Linux | 重组 16 字节特征包、检查 CRC 与传输状态、标准化输入、调用 NPU、读取分数并取最高分类别 |
| ZG330 NPU | 执行编译后的分类网络，输出 17 个 logits |
| R4 板端策略 | 连续 3 个有效、相邻且同类的异常周期确认后，生成模型参考下降请求 |
| PC 桥接 | 串口连接 F4，SSH 连接板载 ARM，把本次诊断与策略结果交给 MATLAB |

这里的 ARM 指悟净 Lite 上运行 Linux 的处理器；F407 是另一块通过 SPI 与 FPGA 连接的 MCU。

R4 当前运行的是**电机模型与真实计算板卡的联合验证**。参考下降作用于 Simulink 模型；使用时按该模式理解结果和操作范围。

## 3. 模型与算子怎样工作

### 3.1 输入、输出和分类含义

每次输入为一个有效完整电周期的 B、C 电流均值，单位 A：

```text
原始特征：[B周期均值, C周期均值]
标准化：z[i] = (x[i] - mean[i]) / std[i]
板端模型输入：FP32，NHWC [1, 1, 1, 2]
板端模型输出：FP32，[1, 17]
```

现有模型配套标准化常数位于 [board/motor_feature_protocol.py](board/motor_feature_protocol.py)：

| 项目 | B 特征 | C 特征 |
| --- | --- | --- |
| mean | 8.817522565349967e-06 | -1.1766226041269304e-05 |
| std | 0.391256791915678 | 0.39125679176324335 |

两种特征包格式的处理不同：

- `flags=0`：包内为原始电流均值，板端先标准化再推理。
- `flags=1`：包内已经标准化，板端直接使用，不能再次标准化。
- `npu_testset.json` 的 `inputs` 已经标准化，批测程序直接送入 NPU。

17 类输出的顺序必须保持一致：

| 输出序号（从 1 开始） | 标签 |
| --- | --- |
| 1 | Normal |
| 2–5 | B_+0.1A、B_+0.2A、B_+0.5A、B_+1.0A |
| 6–9 | B_-0.1A、B_-0.2A、B_-0.5A、B_-1.0A |
| 10–13 | C_+0.1A、C_+0.2A、C_+0.5A、C_+1.0A |
| 14–17 | C_-0.1A、C_-0.2A、C_-0.5A、C_-1.0A |

例如 `B_+0.2A` 表示识别到预设的 B 相电流采样正向偏移档位。输出是分类得分，可为负值；代码使用 Argmax 取最高分的类别。**logits 不是百分比置信度**；最高分并列会被标记，不能作为唯一有效分类。

### 3.2 逻辑网络与编译算子

逻辑结构为 `2 → 16/ReLU → 16/ReLU → 17 logits`，共 609 个参数（560 个权重、49 个偏置）。每样本为 560 次逻辑 MAC，硬件对齐和数据转换另计。

为了适配部署流程，三个全连接层以 1×1 卷积形式表示。这里的“算子”就是网络的一类计算步骤；NPU 加载编译产物后执行这些步骤。

实际模型 [board/motor_bias_mlp17_logits_ZG.json](board/motor_bias_mlp17_logits_ZG.json) 的目标为 `@zhuget(330)`，包含 11 个 `HardOp`：

| 类别 | 数量 | 用途 |
| --- | --- | --- |
| Conv2dNode | 3 | 执行三层线性映射；编译后的算子表不再单列两个 ReLU |
| CastNode | 4 | FP32 接口与内部数值表示之间的转换 |
| ReshapeNode | 3 | 调整张量布局和形状 |
| PruneAxisNode | 1 | 将内部补齐至 32 路的末层结果裁回 17 路 |

此外有 Input、Output 两个图边界节点，它们不计入这 11 个硬件计算算子。模型接口为 FP32，内部卷积张量使用量化表示；不能把接口类型直接理解为所有内部计算都采用 FP32。

普通使用者调用整个模型，无需逐个手动调用算子。NPU 执行由厂商运行库负责，项目负责模型、数据、通信和应用逻辑的配合。

### 3.3 模型文件分别是什么

| 文件 / 目录 | 用途 |
| --- | --- |
| `models/saved/*.mat` | 训练存档、网络、划分及部署参数 |
| `models/saved/motor_bias_mlp17_image_v1.onnx` | 已保存的图像输入版 ONNX，不能直接代替板端编译产物 |
| `board/motor_bias_mlp17_logits_ZG.json` | 编译后的网络描述、算子与接口信息 |
| `board/motor_bias_mlp17_logits_ZG.raw` | 与上述 JSON 配套的参数/部署数据，必须成对使用 |
| `board/npu_testset.json` | 374 条标准化测试输入、标签与对应的量化 Host 参考分数 |
| `models/training_export/` | 训练、ONNX 导出、校准输入生成及历史验证脚本 |

校准用 `.ftmp` 是输入样本，不能当作模型 `.raw` 权重使用。更换网络时，JSON、RAW、标准化常数、类别顺序及测试参考需要一并核对。

## 4. 不接开发板，先做软件检查

在仓库根目录打开终端：

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s motor_link_r4/tests -v
python verification/verify_saved_evidence.py
```

第一条安装检查程序和 PC 桥接所需依赖；第二条运行 R4 软件测试；第三条复核已保存实验的原始点、积分、序号、CRC、决策与反馈时序。

预期为软件测试全部通过、保存证据的复核通过。结果来自仓库内的指定记录，这一步不启动 NPU，也不产生新的硬件测试结果。

## 5. 硬件与运行环境准备

### 5.1 需要的环境

| 位置 | 工具 / 条件 |
| --- | --- |
| Windows 电脑 | Python 3、pyserial、paramiko；桌面界面使用 Tkinter；`py -3` 或 `python` 应能启动所用解释器 |
| MATLAB | 现场记录为 R2020b Update 8；R4 需要 Simulink、原模型所用工具箱与初始化参数 |
| F4 开发 | STM32F407ZG，Keil 工程位于 `motor_raw_replay_v1/STM32/MDK-ARM/`；历史环境为 ARM Compiler 5.06 update 7、STM32F4xx_DFP 3.1.1 |
| FPGA 平台 | 与实际悟净 Lite 对应的厂商工程和已验证的平台镜像；历史工具为 Vivado 2018.3 / Procise |
| 板端 Linux | 可用的 SPI 寄存器映射、ZG330、`/root/run/lib` 下配套运行库 |
| 网络 / 串口 | 电脑能 SSH 登录板卡；F4 串口可用，桥接使用 115200 波特率 |

公开仓库提供自编 FPGA 模块和接入说明；完整 NPU 平台还需要匹配的厂商 IP、镜像和运行库。已有成功运行环境可继续沿用。平台接入见 [fpga/README.md](fpga/README.md)。

### 5.2 连接方式

- 电脑通过 USB 串口连接 F4。
- 电脑通过以太网 / SSH 连接悟净 Lite 的 ARM Linux。
- F4 与 FPGA 通过 SPI Mode 0、MSB first 通信，当前参考构建为 125 kHz。
- F4 侧 3.3 V、FPGA SPI 侧 1.8 V，经电平转换连接并共地；依据实际板卡版本核对接口针位。

当前源码及约束的逻辑引脚对应如下，FPGA 一列为芯片封装管脚名，**不是排针针号**：

| 信号 | F407 GPIO | FPGA 封装管脚 |
| --- | --- | --- |
| SCK | PB3 | AC21 |
| MOSI | PB5 | AC22 |
| MISO | PB4 | AE20 |
| CS_N | PG7 | AE21 |

接线依据为 F4 的 `Core/Src/board.c` 与 `fpga/motor_spi_pins.xdc`。F4 使用 SWD 下载，PB3 供 SPI 使用。

### 5.3 固件与接收服务

F4 原始点固件入口：

`motor_raw_replay_v1/STM32/MDK-ARM/STM32F407_SPI_LED_DEMO.uvprojx`

按该目录说明编译、下载后，串口应出现 **`RAW_HOST V1`** 能力标识。原始波形回放和 R4 都要求该标识；仅能发送现成特征的早期固件不够。

板卡的参考服务目录为 `/root/motor_ai/`。首次在新的、已配置好厂商平台的环境中部署时，可在 **Windows CMD、仓库根目录**执行：

```bat
scp -O -r board root@192.168.126.49:/root/motor_ai_from_repo
```

这会上传到独立目录 `/root/motor_ai_from_repo`，便于与已有现场文件对比。桌面程序和 R4 桥接固定使用 `/root/motor_ai`：对比、备份后，再把需要的脚本和配套模型放入该目录。已有现场目录时先核对版本，不要整目录覆盖。

`192.168.126.49` 和 `COM5` 是参考值，使用实际地址和串口。首次 SSH 连接应核对主机密钥；密码在交互提示中输入。

## 6. 先独立验证 NPU：374 样本批测

这一步只需要板卡上的 NPU 环境，不需要 F4，也不需要启动桌面诊断或 R4。

先正常退出正在使用 NPU 的旧演示或桥接程序。确认 `/root/motor_ai/` 中有以下四个文件：

- `motor_npu_batch.py`
- `motor_bias_mlp17_logits_ZG.json`
- `motor_bias_mlp17_logits_ZG.raw`
- `npu_testset.json`

在 **板卡 Linux 终端**执行：

```bash
cd /root/motor_ai
export LD_LIBRARY_PATH=/root/run/lib:${LD_LIBRARY_PATH:-}
export PYTHONPATH=/root/run/lib:${PYTHONPATH:-}
python3 motor_npu_batch.py --dir /root/motor_ai
```

程序会加载模型，创建一次 ZG330 Session，再依次送入 374 条已标准化 FP32 输入，读取 17 路分数，与标签及量化 Host 参考分类比较。

预期查看：

- `NPU progress: 374/374`：样本执行完毕。
- `NPU accuracy`、`NPU/Host class agreement`：本次实际统计。
- `NPU top-score ties`：最高分并列数量。
- 全部满足脚本条件时打印 `BATCH_PASS`，否则查看 `BATCH_REVIEW` 或异常。
- 结果写入 `npu_batch_年月日_时分秒.json`，中断时也会保存已执行部分。

不要把脚本中定义的通过条件当作本次已测结果；以实际输出和保存 JSON 为准。

### 单样本 smoke 测试何时使用

`motor_npu_smoke.py` 还要求同一次输入对应的 `input.ftmp`（2 个小端 FP32，共 8 字节）和 `33.ftmp`（17 项量化 Host 参考分数）。仓库未提供这对现场文件；需要从同一模型的已核验流程取得，不能临时凑一对输入和参考。新环境优先使用上面的批测入口。

## 7. 桌面操作：原始波形、NPU 输出与 CRC

### 7.1 原始波形回放

1. 退出旧桌面程序、串口助手、R4 桥接，以及由它们启动的旧板端接收服务。
2. 在 Windows 双击 `motor_raw_replay_v1/desktop/start.cmd`，或在仓库根目录执行：

   ```bat
   py -3 motor_raw_replay_v1\desktop\raw_dashboard.py
   ```

3. 填写 F4 串口、板卡 IP 和 root 密码，连接设备。界面通过 SSH 启动板端服务，不需要另开一个相同接收进程。
4. 进入“原始波形回放”，选择 Normal，点击“回放原始周期并诊断”。
5. 等待原始点上传完成，查看 F4 实算 B/C 均值和 PC 黄金积分对照；通过后提交 SPI/NPU。
6. 再选择 B 相或 C 相预设偏移档位，观察分类、实际输入和 17 路输出。
7. 导出本次记录，保留上传点数、误差、序号、分类与时间字段。

数据使用仓库中保存的 Simulink 波形周期；桌面选择的偏移作用于诊断数据。一次请求尚未完成时，等当前进度结束再操作。

### 7.2 NPU 计算页看什么

在“NPU计算”页或“查看NPU算子 / 输出”入口中查看：

- 模型结构及静态编译算子清单。
- 本次板端实收特征、标准化输入、17 个 logits、Top 类别与推理/读取时间。
- 区分静态模型说明与本次实测分数；未收到有效结果时，分数区应为空或提示等待。

内部隐藏层活动没有被读取，界面的结构示意图用于说明网络。

### 7.3 CRC 拦截与恢复怎么演示

1. 先发送一个正常样本，确认当前链路能返回有效分类。
2. 点击“CRC错误包测试”（部分界面显示为“CRC错误包拦截测试”）。
3. 查看“校验错误包已拒绝，未提交 NPU”或对应拒绝事件；本次不应产生有效分类。
4. 再选择 Normal 并发送一次正常样本，确认校验和推理恢复。
5. 导出本次记录，保留错误包与随后正常包的不同序号。

CRC 步骤验证错误数据不会进入推理、下一条有效报文可以继续处理。它检验通信保护行为，不是模型识别率测试。

### 7.4 R2 连续情景

要运行“短暂异常 / 持续偏移 / 恢复”的桌面情景，可使用：

```bat
py -3 motor_demo_r2\desktop\demo_dashboard.py
```

R2 的连续确认与恢复规则在 PC 桌面执行；R4 的三周期确认在板端 Linux 执行，且本轮参考下降锁存到实验结束。两者入口和策略位置不同。

## 8. R4：诊断驱动的模型反馈对照

### 8.1 初始化、准备和预检

在 **MATLAB** 中按原工程的方法加载电机参数和初始化脚本，确保原模型能运行、已保存且处于停止状态。然后在仓库根目录执行：

```matlab
addpath(fullfile(pwd, 'motor_link_r4', 'matlab'));
prepare_motor_link_r4;
check_motor_link_r4;
```

弹窗选择已初始化、零偏移基线使用的原始 SLX。参考模型位于 `simulink/FOC_LADRC_G474_bias_isolated_v2.slx`，配套数据字典与它同目录；不能只打开 SLX 后省略原工程参数初始化。

`prepare` 创建 R4 副本及 `settings.json`；`check` 检查完整状态续接与未来输入修改的等价性。看到 **`R4_PREFLIGHT_PASS`** 后再继续。模型改变后重新准备、预检，不手工修改哈希绕过对应检查。

### 8.2 启动 PC 桥接

关闭旧桌面程序和串口助手；上一模式的板端接收服务也应随其所属程序退出。

若已有基础服务和模型，只补 R4 的两个板端文件，可在 **Windows CMD、仓库根目录**执行：

```bat
scp -O motor_link_r4\board\r4_policy.py motor_link_r4\board\motor_link_service_r4.py root@192.168.126.49:/root/motor_ai/
```

双击 `motor_link_r4/start_bridge.cmd`。按提示输入串口、板卡 IP、密码，等待：

```text
R4_BRIDGE_READY: return to MATLAB and run run_motor_link_r4. Ctrl+C stops.
```

桥接会通过 SSH 启动包装服务，包装服务再启动同目录的 `motor_monitor_service.py`。不要再手动并行启动它。

### 8.3 运行两组对照

保持桥接窗口打开，在 MATLAB 执行：

```matlab
result_dir = run_motor_link_r4;
```

顺序为 `no_feedback`、`with_feedback`。当前默认配置位于 `prepare_motor_link_r4.m`：

| 配置 | 当前默认值 |
| --- | --- |
| 模型停止时间 | 1.5 s |
| 完整周期选择起点 | 0.9 s |
| 诊断 B 通道偏移注入 | 0.96 s 起 +0.2 A |
| 分段续算间隔 | 0.02 s |
| 完整周期内半周期频率相对差门限 | 5% |
| 连续异常确认 | 3 个有效、相邻且同类的异常周期 |
| 模型参考下降时间 | 0.25 s |

第一组收集真实诊断但不执行参考修改；第二组接到板端确认请求后，从下一模型采样点开始下降未来参考，并锁存至本轮结束。后续新模型电流继续送回 F4/NPU。

程序分段续算并等待板卡回复，模型时间与现实等待时间分开记录。低速或频率变化过快导致完整周期条件不足时，会显示 `Diagnosis unavailable`；这表示当前不满足诊断条件，不能当作恢复正常。

### 8.4 查看结果与正常停止

结果目录为 `motor_link_r4/results/R4_时间戳/`：

| 文件 | 内容 |
| --- | --- |
| `status.json` | 完成标志、通过标志与执行阶段 |
| `link_comparison.png` | 两组参考、电流与转速对照 |
| `link_comparison.mat` | 模型数组、周期点、真实返回及策略记录 |
| `evidence.json` | 用于独立复算的完整证据 |
| `action.json` | 源周期、请求序号、板端 token、模型生效时间 |
| `partial_results.mat` | 运行过程中保存的阶段结果，失败时用于排查 |

先检查 `status.completed=true` 和 `status.passed=true`，再运行独立复核：

```bat
python motor_link_r4\tools\audit_run.py "实际结果目录\evidence.json"
```

完整实验结束后，在 PC 桥接窗口按 Ctrl+C。若需中途停止，先中断 MATLAB 运行，再用 Ctrl+C 结束桥接；保留当前结果与日志。中断运行的记录不能当作完整验收通过。

## 9. 常见问题

| 现象 | 排查与处理 |
| --- | --- |
| 找不到 `xir`、`xrt`、`zg330backend` 或共享库 | 确认在板卡 Linux 上运行，`/root/run/lib` 为配套厂商库；按第 6 节设置环境。电脑端安装同名包不能代替板端运行库 |
| `Expected generated ZG330 model` / `Expected hardware-only generated model` | 检查 JSON 目标和算子、JSON/RAW 配对；当前部署目标为 `@zhuget(330)` |
| NPU 打开或输出超时 | 先退出其他 NPU 使用程序，再核对实际平台镜像、运行库及模型版本，保留完整错误输出 |
| SSH `Authentication failed` | 核对板卡 IP、root 登录和密码；在终端先验证 SSH 登录，不把密码写进代码 |
| 主机密钥未知或变化 | 核对实际板卡的 SSH 主机密钥后更新已知主机记录；保留主机校验 |
| 找不到 `RAW_HOST V1` | 核对串口与 F4 原始点固件；不要因此重烧 FPGA 或改 BOOT.bin |
| 串口或板端锁被占用 | 退出占用它的旧界面/桥接；用下方命令查看进程，不删除锁文件 |
| `SPI error counter changed` / `RX_GAP` | 保存日志和计数，检查电平、共地、接线与多个接收进程；排除原因后重启本次请求。保留错误检查 |
| CRC 测试后提示“未提交 NPU” | 错误包测试中的预期保护行为；再发正常样本检查恢复 |
| MATLAB 提示数据字典或变量缺失 | 核对 SLX 与字典位置、MATLAB 搜索路径和原工程初始化参数 |
| R4 提示预检未通过或模型哈希不一致 | 使用当前模型重新 `prepare`、`check`，排查实际错误；不跳过预检 |
| `Diagnosis unavailable` | 检查完整周期、频率、方向与变化门限；这类周期不计为有效正常分类 |

板端只读查看命令：

```bash
pgrep -af 'motor_monitor_service[.]py|motor_link_service_r4[.]py'
python3 /root/motor_ai/motor_spi_read.py
```

第二条读取 SPI 签名、状态和计数，不写寄存器。运行时需使用匹配的平台寄存器映射。

日志通常位于：

- PC R4：`motor_link_r4/runtime/bridge.log`。
- 板端有效特征结果：`/root/motor_ai/spi_feature_results.jsonl`。
- R4 实验：`motor_link_r4/results/R4_时间戳/`。
- NPU 批测：`/root/motor_ai/npu_batch_时间戳.json`。

## 10. 需要重新训练或更换模型时

训练脚本位于 [models/training_export](models/training_export/README.md)。这些脚本根据历史记录整理，使用前按该目录说明确认数据和工具版本。

1. **恢复或准备数据**：`01_features_and_split_from_raw.m` 从指定原始数据构建特征；已有训练存档可用 `02_restore_dataset_from_saved_model.m` 恢复原划分。基础周期分组保持分离，标准化仅使用训练集参数。
2. **实际训练**：`03_baseline_train_and_save.m` 训练并保存部署 MAT。
3. **导出网络**：`04_export_image_onnx.m` 和 `05_export_logits_onnx.m` 分别导出图像输入版与 logits 版，按脚本选取正确已训练 MAT。
4. **生成校准输入**：`06_calibration_all_training_samples.m` 或 `07_calibration_34_training_samples.m`，按采用的工具流程准备校准清单。
5. **ICraft 处理**：使用与当前 ZG330 平台匹配的 parse、quantize、compile 配置生成最终 JSON/RAW。现有模型记录 ICraft v3.36.1、ONNX opset9、目标 `@zhuget(330)`；最终产物为准。
6. **Host 与 NPU 一致性检查**：为新模型重新生成匹配的输入、类别顺序及 Host 参考，再运行实板批测。
7. **更新应用配套参数**：同步标准化常数、类别表、JSON/RAW、测试参考及文件哈希，再逐项验证桌面回放和 R4。

完整现场 ICraft 命令、TOML 与校准清单尚需与成功环境归档核对，本说明不把未核验的编译参数写成一条可直接照跑的命令。日常演示采用现成配套编译模型即可。

## 11. 保存一次可复查的运行

至少保留所用源码/固件版本、JSON/RAW 的哈希、标准化参数、运行日志、原始输入和结果文件。分别记录：

- NPU 批测是否完成、分类是否与当前参考一致。
- F4 均值与同批原始点黄金积分是否一致。
- CRC 错误包是否被拒绝、正常包能否继续处理。
- R4 预检是否通过、本次 `status.json` 是否完成且通过、独立复核是否通过。

`forward_read_ms` / `forward_and_read_ms` 是 NPU forward、等待及读取输出所测区间；`raw_upload_ms`、`pc_roundtrip_ms` 和模型时间使用各自定义。引用性能结果时保留对应字段和测量条件。

更新时间：2026-11-04。
