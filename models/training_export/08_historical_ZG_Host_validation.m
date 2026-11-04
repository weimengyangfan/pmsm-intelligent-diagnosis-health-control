% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
%% 历史专用路径及dump节点33保持原样，使用前核对模型版本；这是Host验证。

%% History batch 117
root = ['C:\Users\admin\moderntcn_cls_v3.36.1\' ...
'moderntcn_cls_icraft\2_compile'];
% 复用之前保存的测试输入和标签
oldTestDir = fullfile(root, ...
'motor_mlp17_build_noimg', 'test_20261030_214659');
resultPath = fullfile(oldTestDir, 'host_test_results.mat');
assert(exist(resultPath,'file') == 2, ...
'找不到原测试结果：%s', resultPath);
p = load(resultPath, 'trueLabels', 'classes', 'testX');
trueLabels = p.trueLabels(:);
classes = p.classes(:);
N = numel(trueLabels);
% 新的 ZG 模型
buildDir = fullfile(root, 'motor_mlp17_logits_ZG_build');
exe = 'C:\Icraft\CLI v3.36.1\bin\icraft-run.exe';
jsonPath = fullfile(buildDir, ...
'motor_bias_mlp17_logits_quantized.json');
rawPath = fullfile(buildDir, ...
'motor_bias_mlp17_logits_quantized.raw');
assert(exist(exe,'file') == 2, '找不到 icraft-run.exe');
assert(exist(jsonPath,'file') == 2, '找不到 ZG 量化 JSON');
assert(exist(rawPath,'file') == 2, '找不到 ZG 量化 RAW');
testDir = fullfile(buildDir, ...
['test_' datestr(now,'yyyymmdd_HHMMSS')]);
mkdir(testDir);
scores = zeros(N,numel(classes));
predLabels = cell(N,1);
for k = 1:N
inputPath = fullfile(oldTestDir, ...
sprintf('%04d',k), 'input.ftmp');
assert(exist(inputPath,'file') == 2, ...
'找不到测试输入：%s', inputPath);
caseDir = fullfile(testDir,sprintf('%04d',k));
mkdir(caseDir);
logFile = fullfile(caseDir,'run.log');
% 每条输入独立启动进程，沿用之前已跑通的方式
cmd = sprintf([ ...
'cmd /d /s /c ""%s" --json "%s" --raw "%s" ' ...
'--input "%s" --backends Host --dump_format SFT ' ...
'--dump_output --dump_ftmp 33 --log_path "%s" ' ...
'> "%s" 2>&1"'], ...
exe,jsonPath,rawPath,inputPath,caseDir,logFile);
status = system(cmd);
if status ~= 0
if exist(logFile,'file') == 2
fprintf('%s\n',fileread(logFile));
end
error('第 %d 条推理失败，已停止。日志：%s',k,logFile);
end
outputPath = fullfile(caseDir, ...
'motor_bias_mlp17_logits','ftmpSFT','33.ftmp');
assert(exist(outputPath,'file') == 2, ...
'找不到输出文件：%s；请查看：%s',outputPath,logFile);
values = sscanf(fileread(outputPath),'%f');
assert(numel(values) == numel(classes) && ...
all(isfinite(values)), ...
'第 %d 条输出异常：应有 %d 个有限分数。', ...
k,numel(classes));
scores(k,:) = values.';
[~,label] = max(values);
predLabels{k} = classes{label};
if mod(k,25) == 0 || k == N
fprintf('ZG Host 测试进度：%d/%d\n',k,N);
drawnow;
end
end
correct = strcmp(predLabels,trueLabels);
fprintf('\nZG INT8 Host准确率：%.2f%%（%d/%d）\n', ...
100*mean(correct),nnz(correct),N);
for c = 1:numel(classes)
pick = strcmp(trueLabels,classes{c});
fprintf('%-10s：召回率 %.2f%%（%d条）\n', ...
classes{c},100*mean(correct(pick)),nnz(pick));
end
wrong = find(~correct);
fprintf('误分类数：%d\n',numel(wrong));
if ~isempty(wrong)
disp(table(wrong,trueLabels(wrong),predLabels(wrong), ...
'VariableNames',{'Index','TrueLabel','PredLabel'}));
end
sortedScores = sort(scores,2,'descend');
tieCount = nnz(sortedScores(:,1) == sortedScores(:,2));
fprintf('最高分并列的样本数：%d\n',tieCount);
testX = p.testX;
save(fullfile(testDir,'host_test_results.mat'), ...
'scores','predLabels','trueLabels','classes', ...
'correct','testX','tieCount','jsonPath','rawPath');
fprintf('结果已保存：%s\n',testDir);
