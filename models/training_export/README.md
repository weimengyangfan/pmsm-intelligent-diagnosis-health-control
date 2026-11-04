# 训练与导出恢复补充包

依据上传的History.xml恢复。history_batches保存相关命令原文；入口脚本仅整理依赖、补文件选择和取消检查。恢复记录不是新的实验结果。本机没有MATLAB，本次未重新训练、导出或上板。

## 放到哪里
解压后把06_AI模型/训练与导出合并到正在补齐的工程同名位置。保留你已从成功现场复制的R4程序、sldd、raw等文件。此包无需替换整套工程。

## 现在只需打包，暂不重训
- 若有已训练的 motor_bias_mlp17_20261030_164321.mat，01可以先不运行。02从其中dataset恢复原划分，并检查标准化参数；03才会实际训练并弹出新部署MAT保存窗口。
- 01使用 motor_normal_angle_v1.mat、motor_B_bias_raw_v3.mat、motor_C_bias_raw_v3.mat。这是当前17类流水线的原始输入；早期motor_bias_raw.mat不是这三份数据的替代品。
- 04/05从已训练MAT导出图像输入版和logits版ONNX，均保留已有权重。05对应后来的motor_bias_mlp17_logits_v1.onnx。标准化仍在网络外部，使用deploy.featureMean/featureStd。
- 06生成全部训练样本的FP32小端校准输入；07生成每类首尾两条、共34条的小校准集。ftmp是输入样本，不能当作部署模型raw参数权重。
- 08/09是历史ICraft Host验证和测试集导出，包含固定目录与dump节点33，需核对实际模型后使用；它们不等于实板NPU运行。

## 从历史恢复出的设置
完整电周期按时间梯形积分得到B/C均值；频率至少10Hz，周期内变化不超过5%，满足条件后等待0.1s。按所有故障共同基础周期分组，按时间先后约60%/20%/20%划分。标准化参数只使用训练集。
MLP：2输入 - 16/ReLU - 16/ReLU - 17输出；rng(42)，Adam，初始学习率0.003，最多600轮，batch64，CPU，ValidationPatience60。图像输入转换为1x1x2；ONNX Opset9；logits导出去除Softmax，组装用回归输出层，不额外训练。

## 历史记录如何解释
100-107和109批导出命令有error标记，未放入可执行流程；110和115没有error标记，并分别对应图像输入和logits导出代码。没有error标记本身不证明结果正确，仍需已有模型或运行输出核对。
原批次、来源SHA256和所有整理改动见PROVENANCE.json。脚本中打印的准确率是实际运行后计算，未预填成功值。

## 仍需收集
History.xml未包含Windows CMD中的完整parse/quantize/compile命令及TOML。
历史ICraft工作目录：C:\Users\admin\moderntcn_cls_v3.36.1\moderntcn_cls_icraft\2_compile。
优先收集其中motor_mlp17_logits_ZG_build相关配置、完整日志、最终JSON/RAW及qtset标定列表；保留你当前成功部署文件。

## 与已有MAT的交叉核对
已用Python读取MAT存档，核对1819x2特征、17类、1088/357/374划分、基础周期集合不交叉，并复算训练集标准化及测试输入，误差符合阈值。详见VALIDATION.json。此核对不代替MATLAB运行验证。
