% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
%% 整理新增的入口：从已有部署MAT恢复历史训练数据和原划分，无需重新采集
[modelFile,modelDir]=uigetfile('*.mat','选择 motor_bias_mlp17_时间戳.mat');
assert(~isequal(modelFile,0),'已取消选择');
p=load(fullfile(modelDir,modelFile),'deploy','dataset');
assert(isfield(p,'dataset') && isfield(p,'deploy'),'需要含 deploy 和 dataset 的部署MAT');
d=p.dataset;
required={'X','Y','classNames','sourceCycle','trainMask','valMask','testMask','cycleResult','readyMask'};
assert(all(isfield(d,required)),'保存的数据集字段不完整');
X=double(d.X); Y=double(d.Y(:)); classNames=d.classNames;
sourceCycle=d.sourceCycle(:);
trainMask=logical(d.trainMask(:));valMask=logical(d.valMask(:));testMask=logical(d.testMask(:));
assert(size(X,2)==2 && numel(Y)==size(X,1),'样本维度不匹配');
assert(all(isfinite(X(:))) && all(sum([trainMask,valMask,testMask],2)==1),'数据或样本划分无效');
assert(isempty(intersect(unique(sourceCycle(trainMask)),unique(sourceCycle(valMask)))) && ...
 isempty(intersect(unique(sourceCycle(trainMask)),unique(sourceCycle(testMask)))) && ...
 isempty(intersect(unique(sourceCycle(valMask)),unique(sourceCycle(testMask)))), ...
 '基础周期在训练、验证、测试集间重叠');
featureMean=mean(X(trainMask,:),1);
featureStd=std(X(trainMask,:),0,1);featureStd(featureStd<1e-12)=1;
assert(max(abs(featureMean-double(p.deploy.featureMean)))<1e-9 && ...
 max(abs(featureStd-double(p.deploy.featureStd)))<1e-9,'重算标准化参数与部署存档不同');
Xscaled=(X-featureMean)./featureStd;
cycleResult=d.cycleResult;readyMask=d.readyMask;
fprintf('恢复样本%d，类别%d，训练/验证/测试=%d/%d/%d\n', ...
 size(X,1),numel(classNames),nnz(trainMask),nnz(valMask),nnz(testMask));
