function check_motor_link_r4()
% No hardware. Prove state continuation AND future input changes on this model.
config=R4.config;root=R4.root;
test_r4_algorithms;
original=pwd;restore=onCleanup(@()cd(original)); %#ok<NASGU>
addpath(config.source_folder);load_system(config.prepared_model);cd(config.source_folder);
model=config.model_name;
status=struct('version','R4.0.0','passed',false,'stage','starting', ...
    'matlab_version',version,'prepared_model_sha256',config.prepared_model_sha256, ...
    'hardware_executed',false,'simulation_executed',false);
output=fullfile(root,'preflight');if ~isfolder(output),mkdir(output);end
R4.write(fullfile(output,'status.json'),status);
try
    neutral=R4.gate(config,[]);
    fprintf('R4 preflight 1/4: continuous neutral simulation.\n');
    [continuous,~]=R4.step(model,config.stop_time_s,[],neutral);
    fprintf('R4 preflight 2/4: segmented neutral simulation with complete state.\n');
    op=[];segmented=struct();
    for stop=[.9 1.0 config.stop_time_s]
        [part,op]=R4.step(model,stop,op,neutral);segmented=R4.append(segmented,part);
    end
    neutral_error=R4.compare(continuous,segmented);
    assert(neutral_error.RPM<1e-3 && neutral_error.theta<1e-5 ...
        && neutral_error.R4_RawB<1e-5 && neutral_error.R4_RawC<1e-5, ...
        'State continuation differs from uninterrupted simulation; do not connect hardware yet.');
    fprintf('R4 preflight 3/4: continuous scheduled ramp (software test only).\n');
    test_activation=1.0;changed=R4.gate(config,test_activation);
    [dynamic_continuous,~]=R4.step(model,config.stop_time_s,[],changed);
    fprintf('R4 preflight 4/4: restore neutral state, change ONLY future input.\n');
    [part,op]=R4.step(model,.94,[],neutral);dynamic_segmented=part;
    [part,op]=R4.step(model,1.10,op,changed);dynamic_segmented=R4.append(dynamic_segmented,part);
    [part,~]=R4.step(model,config.stop_time_s,op,changed);dynamic_segmented=R4.append(dynamic_segmented,part);
    dynamic_error=R4.compare(dynamic_continuous,dynamic_segmented);
    assert(dynamic_error.RPM<1e-3 && dynamic_error.theta<1e-5 ...
        && dynamic_error.R4_AppliedCommand<1e-5, ...
        'Changing future input while restoring state is not equivalent on this model.');
    tail=dynamic_segmented.R4_AppliedCommand.time>=test_activation+config.ramp_time_s;
    assert(any(tail) && max(abs(dynamic_segmented.R4_AppliedCommand.data(tail)))<1e-4, ...
        'Future gate change was not applied; no closed-loop claim allowed.');
    pre=dynamic_segmented.RPM.time<test_activation;
    pre_error=max(abs(dynamic_segmented.RPM.data(pre)-interp1(continuous.RPM.time,continuous.RPM.data,dynamic_segmented.RPM.time(pre))));
    assert(pre_error<1e-3,'Scheduled ramp altered the history before activation.');
    status.passed=true;status.stage='passed';status.simulation_executed=true;
    status.neutral_error=neutral_error;status.dynamic_error=dynamic_error;
    status.pre_activation_rpm_error=pre_error;
    status.matlab_execution_required=false;
    save(fullfile(output,'continuation_check.mat'),'continuous','segmented', ...
        'dynamic_continuous','dynamic_segmented','config','status','-v7');
    R4.write(fullfile(output,'status.json'),status);
    fprintf('R4_PREFLIGHT_PASS: neutral RPM error %.3g, changed-input RPM error %.3g rpm\n', ...
        neutral_error.RPM,dynamic_error.RPM);
    fprintf('No hardware was used. You may proceed to the bridge installation steps.\n');
catch exception
    status.stage='failed';status.failure_message=exception.message;
    R4.write(fullfile(output,'status.json'),status);
    fprintf(2,'R4_PREFLIGHT_FAILED: no success claimed; do not proceed to hardware.\n');
    rethrow(exception);
end
end
