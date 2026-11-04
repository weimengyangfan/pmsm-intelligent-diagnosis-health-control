% 取所有故障类别共同拥有的周期
commonIds = intersect(unique(BcycleId),unique(CcycleId));
for g = unique(Bgroup(:))'
commonIds = intersect(commonIds,BcycleId(Bgroup==g));
end
for g = unique(Cgroup(:))'
commonIds = intersect(commonIds,CcycleId(Cgroup==g));
end
commonIds = sort(commonIds);
assert(numel(unique(Bgroup))==8 && ...
numel(unique(Cgroup))==8, '故障类别数量不是8+8');
% 正常类：使用同样的周期
X = [meanB(commonIds),meanC(commonIds)];
Y = ones(numel(commonIds),1);
sourceCycle = commonIds(:);
classNames = {'Normal'};
% B相8类，标签2~9
bg = unique(Bgroup(:))';
for j = 1:numel(bg)
mask = Bgroup==bg(j) & ismember(BcycleId,commonIds);
bias = unique(Bbias(mask));
assert(numel(bias)==1,'B相类别偏置不唯一');
X = [X;Bfeatures(mask,:)];
Y = [Y;repmat(1+j,nnz(mask),1)];
sourceCycle = [sourceCycle;BcycleId(mask)];
classNames{end+1} = sprintf('B_%+.1fA',bias);
end
% C相8类，标签10~17
cg = unique(Cgroup(:))';
for j = 1:numel(cg)
mask = Cgroup==cg(j) & ismember(CcycleId,commonIds);
bias = unique(Cbias(mask));
assert(numel(bias)==1,'C相类别偏置不唯一');
X = [X;Cfeatures(mask,:)];
Y = [Y;repmat(9+j,nnz(mask),1)];
sourceCycle = [sourceCycle;CcycleId(mask)];
classNames{end+1} = sprintf('C_%+.1fA',bias);
end
assert(all(isfinite(X(:))),'特征含NaN或Inf');
% 按基础周期的时间顺序划分约60%/20%/20%
N = numel(commonIds);
assert(N>=10,'共同周期过少');
nTrain = floor(0.6*N);
nVal = floor(0.2*N);
trainIds = commonIds(1:nTrain);
valIds = commonIds(nTrain+1:nTrain+nVal);
testIds = commonIds(nTrain+nVal+1:end);
trainMask = ismember(sourceCycle,trainIds);
valMask = ismember(sourceCycle,valIds);
testMask = ismember(sourceCycle,testIds);
% 标准化参数只从训练集计算
featureMean = mean(X(trainMask,:),1);
featureStd = std(X(trainMask,:),0,1);
featureStd(featureStd<1e-12) = 1;
Xscaled = (X-featureMean)./featureStd;
fprintf('共同周期数：%d\n',N);
fprintf('总样本：%d，特征数：%d，类别数：%d\n', ...
size(X,1),size(X,2),numel(classNames));
fprintf('训练：%d，验证：%d，测试：%d\n', ...
nnz(trainMask),nnz(valMask),nnz(testMask));
for k = 1:numel(classNames)
fprintf('%-10s：%d条\n',classNames{k},nnz(Y==k));
end
