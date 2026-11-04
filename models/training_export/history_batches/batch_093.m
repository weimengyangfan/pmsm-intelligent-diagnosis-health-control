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
