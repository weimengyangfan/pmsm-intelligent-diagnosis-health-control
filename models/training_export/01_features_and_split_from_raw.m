% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
[angleFile,angleDir]=uigetfile('*.mat','选择 motor_normal_angle_v1.mat');
assert(~isequal(angleFile,0),'已取消选择');
angleCheck=load(fullfile(angleDir,angleFile));
assert(isfield(angleCheck,'normalAngle'),'文件缺少 normalAngle 结构体');

%% History batch 88
n = angleCheck.normalAngle;
t  = double(n.timeTheta(:));
th = unwrap(double(n.theta(:)));
ib = double(n.IB(:));
ic = double(n.IC(:));
assert(numel(t)==numel(ib) && numel(t)==numel(ic), ...
'电流与角度长度不一致');
assert(all(isfinite(ib)) && all(isfinite(ic)), ...
'电流中存在NaN或Inf');
% 根据角度变化判断方向；低于0.5 Hz的区间暂不使用
f = diff(th)./diff(t)/(2*pi);
direction = sign(f);
direction(abs(f)<0.5) = 0;
% 分开处理正转、反转以及停转区间
edges = [1; find(diff(direction)~=0)+1; numel(direction)+1];
% 每行：[开始时间 结束时间 方向 平均频率 B均值 C均值]
cycleResult = zeros(0,6);
for s = 1:numel(edges)-1
first = edges(s);
last  = edges(s+1)-1;
dir = direction(first);
if dir == 0
continue
end
idx = (first:last+1)';
angleForward = dir*th(idx);  % 反转也转换成递增角度
% 寻找该连续区间内完整的2*pi边界
kFirst = ceil(angleForward(1)/(2*pi));
kLast  = floor(angleForward(end)/(2*pi));
if kLast <= kFirst
continue
end
boundaries = (kFirst:kLast)'*2*pi;
crossTime = interp1(angleForward, t(idx), boundaries, 'linear');
for j = 1:numel(crossTime)-1
ta = crossTime(j);
tz = crossTime(j+1);
inside = t>ta & t<tz;
tt = [ta; t(inside); tz];
% 插入周期边界处的电流，再按时间积分求均值
bb = [interp1(t,ib,ta); ib(inside); interp1(t,ib,tz)];
cc = [interp1(t,ic,ta); ic(inside); interp1(t,ic,tz)];
cycleResult(end+1,:) = [ta, tz, dir, ...
dir/(tz-ta), trapz(tt,bb)/(tz-ta), ...
trapz(tt,cc)/(tz-ta)];
end
end
assert(~isempty(cycleResult), '没有找到可用的完整周期');
meanB = cycleResult(:,5);
meanC = cycleResult(:,6);
meanA = -meanB-meanC;
fprintf('完整周期数：%d，正转：%d，反转：%d\n', ...
size(cycleResult,1), sum(cycleResult(:,3)>0), ...
sum(cycleResult(:,3)<0));
fprintf('完整周期均值的标准差：A=%.6f，B=%.6f，C=%.6f A\n', ...
std(meanA), std(meanB), std(meanC));
fprintf('完整周期均值的最大绝对值：A=%.6f，B=%.6f，C=%.6f A\n', ...
max(abs(meanA)), max(abs(meanB)), max(abs(meanC)));
figure('Name','正常电流：完整周期均值');
plot(mean(cycleResult(:,1:2),2), ...
[meanA,meanB,meanC], '.-');
grid on;
xlabel('时间 / s');
ylabel('每个完整周期的电流均值 / A');
legend('A相重构','B相','C相','Location','best');

%% History batch 89
% 分析每个完整周期内的转速变化
cycleCount = size(cycleResult,1);
speedVariation = zeros(cycleCount,1);
minFrequency = zeros(cycleCount,1);
for k = 1:cycleCount
ta = cycleResult(k,1);
tz = cycleResult(k,2);
% f是上一段代码算出的每个采样间隔的电频率
midTime = (t(1:end-1)+t(2:end))/2;
inCycle = midTime >= ta & midTime < tz;
absF = abs(f(inCycle));
minFrequency(k) = min(absF);
speedVariation(k) = ...
(max(absF)-min(absF))/mean(absF);
end
% 暂定筛选条件：周期内频率至少10Hz，变化幅度不超过5%
% 这只是评估稳速区间，不代表低速和动态工况已解决
steadyMask = minFrequency >= 10 & speedVariation <= 0.05;
fprintf('全部完整周期：%d\n', cycleCount);
fprintf('暂符合稳速条件：%d\n', nnz(steadyMask));
if any(steadyMask)
steadyMeans = [meanA(steadyMask), ...
meanB(steadyMask), meanC(steadyMask)];
fprintf('稳速周期均值标准差：A=%.6f，B=%.6f，C=%.6f A\n', ...
std(steadyMeans,0,1));
fprintf('稳速周期均值最大绝对值：A=%.6f，B=%.6f，C=%.6f A\n', ...
max(abs(steadyMeans),[],1));
end
% 列出正常数据中偏差最大的10个周期，查看其速度变化
peakMean = max(abs([meanA,meanB,meanC]),[],2);
[~,order] = sort(peakMean,'descend');
pick = order(1:min(10,cycleCount));
disp(table(cycleResult(pick,1), cycleResult(pick,2), ...
peakMean(pick), minFrequency(pick), ...
100*speedVariation(pick), ...
'VariableNames', {'Start_s','End_s','MaxMean_A', ...
'MinFreq_Hz','SpeedVariation_pct'}));

%% History batch 91
settleTime = 0.1;      % 暂定恢复时间：100 ms
readyMask = false(size(steadyMask));
stableStart = NaN;
for k = 1:size(cycleResult,1)
if ~steadyMask(k)
stableStart = NaN;
continue
end
% 数据中断或方向改变，重新计时
if k > 1
gap = cycleResult(k,1) - cycleResult(k-1,2);
changedDirection = ...
cycleResult(k,3) ~= cycleResult(k-1,3);
if gap > 1e-8 || changedDirection
stableStart = NaN;
end
end
if isnan(stableStart)
stableStart = cycleResult(k,1);
end
% 整个用于诊断的周期，都在等待时间之后
readyMask(k) = ...
cycleResult(k,1) - stableStart >= settleTime;
end
fprintf('等待100 ms后，可诊断周期：%d / %d\n', ...
nnz(readyMask), numel(readyMask));
if any(readyMask)
readyMeans = [meanA(readyMask), ...
meanB(readyMask), meanC(readyMask)];
fprintf('均值标准差：A=%.6f，B=%.6f，C=%.6f A\n', ...
std(readyMeans,0,1));
fprintf('均值最大绝对值：A=%.6f，B=%.6f，C=%.6f A\n', ...
max(abs(readyMeans),[],1));
else
disp('没有符合条件的周期');
end
[biasFile,biasDir]=uigetfile('*.mat','选择 motor_B_bias_raw_v3.mat');
assert(~isequal(biasFile,0),'已取消选择');
biasCheck=load(fullfile(biasDir,biasFile));
assert(isfield(biasCheck,'bSweep'),'文件缺少 bSweep 结构体');

%% History batch 93
bSweep = biasCheck.bSweep;
cycleIds = find(readyMask);
% 特征列：[B相周期均值，C相周期均值]
% A相可由 -B-C 得到，不作为重复特征
Bfeatures = zeros(0,2);
Bbias = zeros(0,1);
BcycleId = zeros(0,1);
Bgroup = zeros(0,1);
for g = 1:numel(bSweep)
s = bSweep(g);
tt = double(s.time(:));
rawB = double(s.rawB(:));
rawC = double(s.rawC(:));
faultB = double(s.faultB(:));
faultC = double(s.faultC(:));
bias = double(s.bias);
assert(all(diff(tt)>0), '第%d组时间轴不递增', g);
assert(all([numel(rawB),numel(rawC), ...
numel(faultB),numel(faultC)] == numel(tt)), ...
'第%d组数据长度不一致', g);
count = 0;
for j = 1:numel(cycleIds)
k = cycleIds(j);
ta = cycleResult(k,1);
tz = cycleResult(k,2);
if ta < tt(1) || tz > tt(end)
continue
end
inside = tt>ta & tt<tz;
tq = [ta; tt(inside); tz];
rb = interp1(tt,rawB,tq);
rc = interp1(tt,rawC,tq);
fb = interp1(tt,faultB,tq);
fc = interp1(tt,faultC,tq);
% 整圈均已施加指定B相偏置，C相无偏置
tol = 1e-6;
if any(~isfinite([rb;rc;fb;fc])) || ...
any(abs((fb-rb)-bias)>tol) || ...
any(abs(fc-rc)>tol)
continue
end
% 确认能复用正常数据的角度周期与稳速筛选
refB = interp1(t,ib,tq);
refC = interp1(t,ic,tq);
assert(max(abs(rb-refB))<tol && ...
max(abs(rc-refC))<tol, ...
'第%d组与角度基准不一致，不能复用周期边界',g);
features = [trapz(tq,fb),trapz(tq,fc)]/(tz-ta);
Bfeatures(end+1,:) = features;
Bbias(end+1,1) = bias;
BcycleId(end+1,1) = k;
Bgroup(end+1,1) = g;
count = count+1;
end
fprintf('B相偏置 %+g A：有效周期 %d\n',bias,count);
end
fprintf('B相故障特征总数：%d，特征维数：%d\n', ...
size(Bfeatures,1),size(Bfeatures,2));

%% History batch 94
[cFile,cDir] = uigetfile('*.mat', ...
'选择 motor_C_bias_raw_v3.mat');
if isequal(cFile,0)
error('未选择文件，请重新运行本段');
end
cData = load(fullfile(cDir,cFile));
% 自动找到包含故障数据的结构体，避免猜变量名
names = fieldnames(cData);
matches = {};
required = {'bias','time','rawB','rawC','faultB','faultC'};
for q = 1:numel(names)
value = cData.(names{q});
if isstruct(value) && all(isfield(value,required))
matches{end+1} = names{q};
end
end
assert(numel(matches)==1, '未找到唯一的C相故障数据结构体');
cSweep = cData.(matches{1});
Cfeatures = zeros(0,2);
Cbias = zeros(0,1);
CcycleId = zeros(0,1);
Cgroup = zeros(0,1);
cycleIds = find(readyMask);
for g = 1:numel(cSweep)
s = cSweep(g);
tt = double(s.time(:));
rawB = double(s.rawB(:));
rawC = double(s.rawC(:));
faultB = double(s.faultB(:));
faultC = double(s.faultC(:));
bias = double(s.bias);
assert(all(diff(tt)>0), '第%d组时间轴不递增',g);
assert(all([numel(rawB),numel(rawC), ...
numel(faultB),numel(faultC)]==numel(tt)), ...
'第%d组数据长度不一致',g);
count = 0;
for j = 1:numel(cycleIds)
k = cycleIds(j);
ta = cycleResult(k,1);
tz = cycleResult(k,2);
if ta<tt(1) || tz>tt(end)
continue
end
inside = tt>ta & tt<tz;
tq = [ta;tt(inside);tz];
rb = interp1(tt,rawB,tq);
rc = interp1(tt,rawC,tq);
fb = interp1(tt,faultB,tq);
fc = interp1(tt,faultC,tq);
% 整圈C相偏置已生效，B相无偏置
tol = 1e-6;
if any(~isfinite([rb;rc;fb;fc])) || ...
any(abs(fb-rb)>tol) || ...
any(abs((fc-rc)-bias)>tol)
continue
end
refB = interp1(t,ib,tq);
refC = interp1(t,ic,tq);
assert(max(abs(rb-refB))<tol && ...
max(abs(rc-refC))<tol, ...
'第%d组与角度基准不一致，不能复用周期边界',g);
Cfeatures(end+1,:) = ...
[trapz(tq,fb),trapz(tq,fc)]/(tz-ta);
Cbias(end+1,1) = bias;
CcycleId(end+1,1) = k;
Cgroup(end+1,1) = g;
count = count+1;
end
fprintf('C相偏置 %+g A：有效周期 %d\n',bias,count);
end
fprintf('C相故障特征总数：%d，特征维数：%d\n', ...
size(Cfeatures,1),size(Cfeatures,2));

%% History batch 95
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
