% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
%% 先运行01或02得到数据；本脚本会实际重新训练，打包时无需执行
assert(exist('Xscaled','var')==1 && exist('classNames','var')==1, ...
 '先运行01_features_and_split_from_raw或02_restore_dataset_from_saved_model');

%% History batch 96
% 仅使用训练集计算17个类别中心
numClasses = numel(classNames);
classCenters = zeros(numClasses,size(Xscaled,2));
for k = 1:numClasses
classCenters(k,:) = mean( ...
Xscaled(trainMask & Y==k,:),1);
end
% 计算所有样本到各类别中心的平方距离
distance = zeros(size(Xscaled,1),numClasses);
for k = 1:numClasses
distance(:,k) = sum( ...
(Xscaled-classCenters(k,:)).^2,2);
end
[~,baselinePred] = min(distance,[],2);
fprintf('基线训练准确率：%.2f%%\n', ...
100*mean(baselinePred(trainMask)==Y(trainMask)));
fprintf('基线验证准确率：%.2f%%\n', ...
100*mean(baselinePred(valMask)==Y(valMask)));
fprintf('基线测试准确率：%.2f%%\n', ...
100*mean(baselinePred(testMask)==Y(testMask)));
% 各类别测试召回率
for k = 1:numClasses
mask = testMask & Y==k;
fprintf('%-10s：测试召回率 %.2f%%（%d条）\n', ...
classNames{k}, ...
100*mean(baselinePred(mask)==k),nnz(mask));
end
% 显示测试集误分类
wrong = find(testMask & baselinePred~=Y);
fprintf('测试集误分类数：%d\n',numel(wrong));
if ~isempty(wrong)
show = wrong(1:min(20,numel(wrong)));
labels = classNames(:);
disp(table(sourceCycle(show), ...
X(show,1),X(show,2), ...
labels(Y(show)),labels(baselinePred(show)), ...
'VariableNames', ...
{'CycleId','MeanB_A','MeanC_A','TrueClass','PredClass'}));
end
% 检查后续训练神经网络可用的函数
fprintf('\n神经网络函数可用性：\n');
fprintf('trainNetwork：%d\n',exist('trainNetwork','file')==2);
fprintf('patternnet：%d\n',exist('patternnet','file')==2);

%% History batch 97
rng(42);  % 固定随机种子，方便复现
% 固定类别顺序，避免标签与输出端口错位
numClasses = numel(classNames);
classOrder = categorical( ...
(1:numClasses)',1:numClasses,classNames);
Ycat = categorical(Y,1:numClasses,classNames);
XTrain = single(Xscaled(trainMask,:));
XVal   = single(Xscaled(valMask,:));
XTest  = single(Xscaled(testMask,:));
YTrain = Ycat(trainMask);
YVal   = Ycat(valMask);
YTest  = Ycat(testMask);
layers = [
featureInputLayer(2, ...
'Normalization','none','Name','input')
fullyConnectedLayer(16,'Name','fc1')
reluLayer('Name','relu1')
fullyConnectedLayer(16,'Name','fc2')
reluLayer('Name','relu2')
fullyConnectedLayer(numClasses,'Name','fc_out')
softmaxLayer('Name','probability')
classificationLayer('Name','classOutput', ...
'Classes',classOrder)
];
iterationsPerEpoch = ceil(size(XTrain,1)/64);
options = trainingOptions('adam', ...
'InitialLearnRate',0.003, ...
'MaxEpochs',600, ...
'MiniBatchSize',64, ...
'Shuffle','every-epoch', ...
'ValidationData',{XVal,YVal}, ...
'ValidationFrequency',iterationsPerEpoch, ...
'ValidationPatience',60, ...
'ExecutionEnvironment','cpu', ...
'Verbose',false, ...
'Plots','training-progress');
[net,trainInfo] = trainNetwork( ...
XTrain,YTrain,layers,options);
% 训练结束后统一评估
predTrain = classify(net,XTrain);
predVal   = classify(net,XVal);
[predTest,testScores] = classify(net,XTest);
fprintf('\nMLP训练准确率：%.2f%%\n', ...
100*mean(predTrain==YTrain));
fprintf('MLP验证准确率：%.2f%%\n', ...
100*mean(predVal==YVal));
fprintf('MLP测试准确率：%.2f%%\n', ...
100*mean(predTest==YTest));
for k = 1:numClasses
mask = YTest==classOrder(k);
fprintf('%-10s：测试召回率 %.2f%%（%d条）\n', ...
classNames{k}, ...
100*mean(predTest(mask)==YTest(mask)),nnz(mask));
end
fprintf('测试误分类数：%d\n',nnz(predTest~=YTest));

%% History batch 98
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
