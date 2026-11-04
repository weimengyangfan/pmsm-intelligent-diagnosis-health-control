% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
%% batch112；仅把固定输出目录改成选择目录
[file,folder] = uigetfile('*.mat','选择MLP部署包');
if isequal(file,0)
error('已取消选择');
end
p = load(fullfile(folder,file),'deploy','dataset');
d = p.dataset;
% 每类从训练集中取首尾两条，共34条
selected = [];
for label = 1:numel(d.classNames)
ids = find(d.trainMask & d.Y==label);
assert(numel(ids)>=2,'某类别训练样本不足');
selected = [selected; ids(1); ids(end)];
end
calibX = single((d.X(selected,:)-p.deploy.featureMean) ...
./p.deploy.featureStd);
assert(all(isfinite(calibX(:))),'校准数据含无效值');
root=uigetdir(pwd,'选择ICraft的2_compile目录');
assert(~isequal(root,0),'已取消选择');
outDir = fullfile(root,'qtset','motor_mlp17_small');
if ~exist(outDir,'dir')
mkdir(outDir);
end
listID = fopen(fullfile(root,'qtset','motor_mlp17_small.txt'),'wt');
assert(listID~=-1,'无法创建清单');
for k = 1:size(calibX,1)
name = sprintf('%04d.ftmp',k-1);
fid = fopen(fullfile(outDir,name),'wb','ieee-le');
assert(fid~=-1,'无法创建样本文件');
fwrite(fid,calibX(k,:),'single');
fclose(fid);
fprintf(listID,'%s\n',name);
end
fclose(listID);
fprintf('小校准集已生成：%d条，每类2条\n',size(calibX,1));
