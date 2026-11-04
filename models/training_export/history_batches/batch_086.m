% 选择之前保存的角度数据文件
[angleFile, angleDir] = uigetfile( ...
'*.mat', '选择 motor_normal_angle_v1.mat');
if isequal(angleFile, 0)
disp('已取消选择');
else
anglePath = fullfile(angleDir, angleFile);
% 查看文件包含的变量
whos('-file', anglePath)
% 放入独立结构体，避免覆盖工作区已有变量
angleCheck = load(anglePath);
% 如果文件只保存了一个结构体，显示其内部字段
angleFields = fieldnames(angleCheck);
if numel(angleFields) == 1 && ...
isstruct(angleCheck.(angleFields{1}))
disp('内部字段：');
disp(fieldnames(angleCheck.(angleFields{1})));
end
end
