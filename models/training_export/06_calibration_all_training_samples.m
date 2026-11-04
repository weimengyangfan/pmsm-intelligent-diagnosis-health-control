% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
%% batch111；仅把固定输出目录改成选择目录
[file, folder] = uigetfile('*.mat','选择保存的MLP部署包');
if isequal(file,0)
error('已取消选择');
end
p = load(fullfile(folder,file),'deploy','dataset');
% 只使用训练集，并应用训练时的标准化
trainX = p.dataset.X(p.dataset.trainMask,:);
calibX = single((trainX-p.deploy.featureMean) ...
./p.deploy.featureStd);
assert(all(isfinite(calibX(:))), '校准数据存在NaN或Inf');
compileDir=uigetdir(pwd,'选择ICraft的2_compile目录');
assert(~isequal(compileDir,0),'已取消选择');
calibDir = fullfile(compileDir,'qtset','motor_mlp17');
if ~exist(calibDir,'dir')
mkdir(calibDir);
end
listPath = fullfile(compileDir,'qtset','motor_mlp17.txt');
listID = fopen(listPath,'wt');
assert(listID~=-1,'无法创建校准清单');
for k = 1:size(calibX,1)
name = sprintf('%04d.ftmp',k-1);
dataID = fopen(fullfile(calibDir,name),'wb','ieee-le');
if dataID == -1
fclose(listID);
error('无法创建校准样本：%s',name);
end
% NHWC=[1,1,1,2]：依次写入B、C两个float32
fwrite(dataID,calibX(k,:),'single');
fclose(dataID);
fprintf(listID,'%s\n',name);
end
fclose(listID);
fprintf('校准数据已生成：%d条，每条8字节\n',size(calibX,1));
fprintf('校准目录：%s\n',calibDir);
fprintf('校准清单：%s\n',listPath);
