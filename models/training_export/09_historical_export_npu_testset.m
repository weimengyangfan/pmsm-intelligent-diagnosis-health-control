% 从上传的History.xml整理；详见README，未经本机MATLAB重跑。
%% 依赖历史Host测试结果目录；使用前核对路径，不代表再次完成NPU测试。

%% History batch 118
root = ['C:\Users\admin\moderntcn_cls_v3.36.1\' ...
'moderntcn_cls_icraft\2_compile'];
buildDir = fullfile(root,'motor_mlp17_logits_ZG_build');
hostDir = fullfile(buildDir,'test_20261030_223239');
inputDir = fullfile(root,'motor_mlp17_build_noimg', ...
'test_20261030_214659');
p = load(fullfile(hostDir,'host_test_results.mat'), ...
'scores','trueLabels','classes');
N = numel(p.trueLabels);
assert(N == 374,'测试样本数量不符');
D.format_version = 1;
D.input_format = 'already_standardized_fp32_BC';
D.classes = cellstr(string(p.classes(:)));
D.true_labels = cellstr(string(p.trueLabels(:)));
D.host_scores = double(p.scores);
D.inputs = zeros(N,2);
for k = 1:N
inputPath = fullfile(inputDir,sprintf('%04d',k),'input.ftmp');
fid = fopen(inputPath,'rb','ieee-le');
assert(fid ~= -1,'无法读取：%s',inputPath);
x = fread(fid,Inf,'single=>double');
fclose(fid);
assert(numel(x) == 2 && all(isfinite(x)), ...
'第%d条输入异常',k);
D.inputs(k,:) = x.';
end
exportPath = fullfile(buildDir,'npu_testset.json');
fid = fopen(exportPath,'w');
assert(fid ~= -1,'无法创建测试数据文件');
fwrite(fid,jsonencode(D),'char');
fclose(fid);
fprintf('已导出%d条已有测试输入：\n%s\n',N,exportPath);
