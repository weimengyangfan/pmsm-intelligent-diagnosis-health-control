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
