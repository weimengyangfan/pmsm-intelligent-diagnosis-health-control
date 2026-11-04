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
