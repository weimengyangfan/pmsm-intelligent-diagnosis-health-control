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
