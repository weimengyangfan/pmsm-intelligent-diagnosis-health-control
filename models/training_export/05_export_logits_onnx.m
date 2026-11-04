% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。

%% History batch 115
[file,folder] = uigetfile('*.mat','选择MLP部署包');
if isequal(file,0)
error('已取消选择');
end
p = load(fullfile(folder,file),'deploy','reference');
originalNet = p.deploy.net;
layers = originalNet.Layers;
% 保留到最后一个全连接层，去掉Softmax和分类输出层
lastFC = find(arrayfun(@(x) ...
isa(x,'nnet.cnn.layer.FullyConnectedLayer'),layers),1,'last');
assert(~isempty(lastFC),'找不到全连接层');
layers = layers(1:lastFC);
% 使用R2020b导出器支持的图像输入
layers(1) = imageInputLayer([1 1 2], ...
'Normalization','none','Name','input');
% 重建全连接层的输入尺寸信息，保留全部权重和偏置
for k = 2:numel(layers)
old = layers(k);
if isa(old,'nnet.cnn.layer.FullyConnectedLayer')
layers(k) = fullyConnectedLayer(size(old.Weights,1), ...
'Name',old.Name, ...
'Weights',old.Weights,'Bias',old.Bias);
end
end
% 回归输出只用于组装网络，不进行训练
layers = [layers; regressionLayer('Name','scores_output')];
netLogits = assembleNetwork(layers);
% 验证浮点类别与原模型一致
x = single(p.reference.networkInput);
xImage = reshape(x.',[1 1 2 size(x,1)]);
logits = predict(netLogits,xImage);
assert(isequal(size(logits),size(p.reference.scores)), ...
'输出尺寸不一致');
[~,newClass] = max(logits,[],2);
[~,oldClass] = max(p.reference.scores,[],2);
fprintf('去除Softmax后的类别一致率：%.2f%%\n', ...
100*mean(newClass==oldClass));
assert(all(newClass==oldClass),'类别不一致，停止导出');
onnxPath = fullfile(folder,'motor_bias_mlp17_logits_v1.onnx');
exportONNXNetwork(netLogits,onnxPath,'OpsetVersion',9);
fprintf('导出成功：\n%s\n',onnxPath);
