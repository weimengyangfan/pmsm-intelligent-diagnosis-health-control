root = ...
'C:\Users\admin\moderntcn_cls_v3.36.1\moderntcn_cls_icraft\2_compile';
% 之前已保存的测试结果及输入
oldTestDir = fullfile(root,'motor_mlp17_build_noimg', ...
'test_20261030_214659');
p = load(fullfile(oldTestDir,'host_test_results.mat'), ...
'trueLabels','classes','testX');
trueLabels = p.trueLabels(:);
classes = p.classes(:);
N = numel(trueLabels);
buildDir = fullfile(root,'motor_mlp17_logits_build');
exe = 'C:\Icraft\CLI v3.36.1\bin\icraft-run.exe';
jsonPath = fullfile(buildDir,'motor_bias_mlp17_logits_quantized.json');
rawPath = fullfile(buildDir,'motor_bias_mlp17_logits_quantized.raw');
testDir = fullfile(buildDir, ...
['test_' datestr(now,'yyyymmdd_HHMMSS')]);
mkdir(testDir);
scores = zeros(N,numel(classes));
predLabels = cell(N,1);
for k = 1:N
% 直接复用上次生成的二进制输入
inputPath = fullfile(oldTestDir,sprintf('%04d',k),'input.ftmp');
assert(exist(inputPath,'file')==2,'找不到测试输入：%s',inputPath);
caseDir = fullfile(testDir,sprintf('%04d',k));
mkdir(caseDir);
logFile = fullfile(caseDir,'run.log');
cmd = sprintf([ ...
'cmd /d /s /c ""%s" --json "%s" --raw "%s" ' ...
'--input "%s" --backends Host --dump_format SFT ' ...
'--dump_output --dump_ftmp 25 --log_path "%s" ' ...
'> "%s" 2>&1"'], ...
exe,jsonPath,rawPath,inputPath,caseDir,logFile);
[status,msg] = system(cmd);
if status~=0
if exist(logFile,'file')
disp(fileread(logFile));
end
error('第%d条运行失败：%s',k,msg);
end
outputPath = fullfile(caseDir,'motor_bias_mlp17_logits', ...
'ftmpSFT','25.ftmp');
assert(exist(outputPath,'file')==2, ...
'未生成输出，请检查：%s',logFile);
values = sscanf(fileread(outputPath),'%f');
assert(numel(values)==numel(classes) && ...
all(isfinite(values)),'第%d条输出无效',k);
scores(k,:) = values.';
[~,label] = max(values);
predLabels{k} = classes{label};
if mod(k,25)==0 || k==N
fprintf('已完成 %d/%d\n',k,N);
drawnow;
end
end
correct = strcmp(predLabels,trueLabels);
fprintf('\n无Softmax INT8 Host准确率：%.2f%%（%d/%d）\n', ...
100*mean(correct),nnz(correct),N);
for k = 1:numel(classes)
mask = strcmp(trueLabels,classes{k});
fprintf('%-10s：召回率 %.2f%%（%d条）\n', ...
classes{k},100*mean(correct(mask)),nnz(mask));
end
wrong = find(~correct);
fprintf('误分类数：%d\n',numel(wrong));
if ~isempty(wrong)
disp(table(wrong,trueLabels(wrong),predLabels(wrong), ...
'VariableNames',{'TestIndex','TrueClass','PredClass'}));
end
sortedScores = sort(scores,2,'descend');
fprintf('最高分并列的样本数：%d\n', ...
nnz(sortedScores(:,1)==sortedScores(:,2)));
testX = p.testX;
save(fullfile(testDir,'host_test_results.mat'), ...
'scores','predLabels','trueLabels','classes','correct','testX');
fprintf('结果已保存：%s\n',testDir);
