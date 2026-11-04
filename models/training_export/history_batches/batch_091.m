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
