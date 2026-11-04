function prepare_motor_link_r4(model_file)
% Select saved original model once; keep all R4 settings on disk.
root=R4.root;original=pwd;restore=onCleanup(@()cd(original)); %#ok<NASGU>
if nargin<1 || isempty(model_file)
    [name,folder]=uigetfile('*.slx','Select original zero-bias model (not an R3/R4 result)');
    if isequal(name,0),return;end
    model_file=fullfile(folder,name);
end
[ok,attributes]=fileattrib(model_file);assert(ok,'Model file missing.');model_file=attributes.Name;
[folder,name]=fileparts(model_file);addpath(folder);load_system(model_file);
assert(strcmp(get_param(name,'Dirty'),'off'),'Save the original model with Ctrl+S first.');
assert(strcmp(get_param(name,'SimulationStatus'),'stopped'),'Stop the original simulation first.');
stamp=[datestr(now,'yyyymmdd_HHMMSS') '_' sprintf('%05d',randi(99999))];
prepared_folder=fullfile(root,'prepared',stamp);mkdir(prepared_folder);
prepared_name=['R4_' stamp];prepared_model=fullfile(prepared_folder,[prepared_name '.slx']);
config=struct('version','R4.0.0','source_model',model_file, ...
    'source_model_sha256',R4.sha(model_file),'prepared_model',prepared_model, ...
    'model_name',prepared_name,'source_folder',folder,'stop_time_s',1.5, ...
    'warmup_s',.9,'chunk_s',.02,'fault_time_s',.96,'bias_B_A',.2, ...
    'ramp_time_s',.25,'max_half_cycle_variation',.05,'rpc_timeout_s',180, ...
    'real_time',false,'hardware_motor_control',false);
copyfile(model_file,prepared_model);load_system(prepared_model);
R4.instrument(prepared_name,config);save_system(prepared_name,prepared_model);cd(original);
assert(strcmp(get_param(prepared_name,'SolverType'),'Fixed-step'),'This version requires the existing fixed-step model.');
step_text=get_param(prepared_name,'FixedStep');
sample = Simulink.data.evalinGlobal(prepared_name, step_text);

if isa(sample, 'Simulink.Parameter')
    sample = sample.Value;
end
assert(isnumeric(sample) && isscalar(sample) && isfinite(sample) && sample>0,'Cannot resolve model fixed step.');
config.sample_s=double(sample);
assert(abs(round(config.chunk_s/sample)*sample-config.chunk_s)<1e-9,'Chunk time must align to model step.');
config.prepared_model_sha256=R4.sha(prepared_model);
R4.write(fullfile(root,'settings.json'),config);
fprintf('R4 prepared COPY: %s\nSettings saved: %s\n',prepared_model,fullfile(root,'settings.json'));
fprintf('No board connection or firmware change. Next: check_motor_link_r4\n');
end
