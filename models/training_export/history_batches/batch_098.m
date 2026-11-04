% 选择保存位置
saveDir = uigetdir(pwd,'选择模型部署包保存文件夹');
if isequal(saveDir,0)
error('已取消保存');
end
% 网络与输入输出约定
deploy = struct;
deploy.net = net;
deploy.featureNames = {'MeanB_A','MeanC_A'};
deploy.featureMean = featureMean;
deploy.featureStd = featureStd;
% 输出顺序以网络实际顺序为准
deploy.outputClasses = cellstr(net.Layers(end).Classes);
% 特征提取条件
deploy.minElectricalFrequency_Hz = 10;
deploy.maxSpeedVariation = 0.05;
deploy.settleTime_s = 0.1;
deploy.averaging = '完整电周期内按时间积分求均值';
deploy.invalidState = '暂不诊断';
% 保存原始特征和划分，方便复现
dataset = struct;
dataset.X = X;
dataset.Y = Y;
dataset.classNames = classNames;
dataset.sourceCycle = sourceCycle;
dataset.trainMask = trainMask;
dataset.valMask = valMask;
dataset.testMask = testMask;
dataset.cycleResult = cycleResult;
dataset.readyMask = readyMask;
% 保存板上对比需要的测试输入与参考输出
reference = struct;
reference.rawFeatures = X(testMask,:);
reference.networkInput = XTest;
reference.trueLabels = cellstr(YTest);
reference.predictedLabels = cellstr(predTest);
reference.scores = testScores;
reference.outputClasses = deploy.outputClasses;
% 时间戳命名，避免覆盖之前的版本
stamp = datestr(now,'yyyymmdd_HHMMSS');
savePath = fullfile(saveDir, ...
['motor_bias_mlp17_' stamp '.mat']);
save(savePath,'deploy','dataset','reference', ...
'trainInfo','classCenters','-v7.3');
fprintf('部署包已保存：\n%s\n',savePath);
% 查看后续导出能力，不执行导出
fprintf('\nMATLAB版本：%s\n',version);
fprintf('exportONNXNetwork 可用：%d\n', ...
exist('exportONNXNetwork','file')==2);
