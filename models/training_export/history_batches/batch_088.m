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
