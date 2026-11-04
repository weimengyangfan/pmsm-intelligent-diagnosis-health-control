[biasFile, biasDir] = uigetfile( ...
'*.mat', '选择 motor_B_bias_raw_v3.mat');
if ~isequal(biasFile,0)
biasPath = fullfile(biasDir,biasFile);
whos('-file',biasPath)
biasCheck = load(biasPath);
names = fieldnames(biasCheck);
for k = 1:numel(names)
value = biasCheck.(names{k});
fprintf('\n变量：%s，类型：%s，尺寸：%s\n', ...
names{k}, class(value), mat2str(size(value)));
if isstruct(value)
disp('结构体字段：');
disp(fieldnames(value));
end
end
end
