function output_dir=run_motor_link_r4()
% Non-real-time model/board linkage. The PC never chooses the diagnosis.
% No MCU reference command is sent: this minimal version bridges to the MODEL.
config=R4.config;root=R4.root;
preflight=R4.read(fullfile(root,'preflight','status.json'));
assert(preflight.passed && strcmp(preflight.prepared_model_sha256,config.prepared_model_sha256), ...
    'A passing check_motor_link_r4 for this prepared model is required.');
original=pwd;restore=onCleanup(@()cd(original)); %#ok<NASGU>
addpath(config.source_folder);load_system(config.prepared_model);cd(config.source_folder);
stamp=[datestr(now,'yyyymmdd_HHMMSS') '_' sprintf('%05d',randi(99999))];
output_dir=fullfile(root,'results',['R4_' stamp]);mkdir(output_dir);
status=struct('version','R4.0.0','stage','starting','completed',false, ...
    'passed',false,'real_time',false,'hardware_motor_control',false, ...
    'simulation_source','newly continued Simulink states, not a frozen replay file', ...
    'decision_source','this run: real NPU + board Linux three-cycle confirmation', ...
    'return_path','board SSH -> PC bridge -> Simulink reference; no MCU execution acknowledgement', ...
    'prepared_model_sha256',config.prepared_model_sha256,'cases_completed',{{}}, ...
    'output_dir',output_dir);
R4.write(fullfile(output_dir,'status.json'),status);
results=struct();figure_handle=[];
try
    R4.rpc(struct('op','ping'),15);
    figure_handle=figure('Name','R4 non-real-time board/model linkage','Color','w', ...
        'Position',[80 50 1150 830]);
    for index=1:2
        if index==1,tag='no_feedback';enabled=false;else,tag='with_feedback';enabled=true;end
        case_id=strrep(char(java.util.UUID.randomUUID),'-','');
        R4.rpc(struct('op','reset','case_id',case_id),15);
        status.stage=['running_' tag];R4.write(fullfile(output_dir,'status.json'),status);
        data=struct();op=[];cursor=config.warmup_s;activation=[];first_alarm=[];
        records={};skips={};stops=config.warmup_s:config.chunk_s:config.stop_time_s;
        stops=unique([stops config.stop_time_s]);
        wall=tic;
        fprintf('\nR4 %s: using new model data and live board decisions.\n',tag);
        for stop=stops
            [part,op]=R4.step(config.model_name,stop,op,R4.gate(config,activation));
            data=R4.append(data,part);
            [cycles,cursor,~]=R4.cycles(data,cursor,config);
            for j=1:numel(cycles)
                cycle=cycles(j);
                if ~cycle.quality
                    R4.rpc(struct('op','gap','case_id',case_id),15);
                    skips{end+1}=rmfield(cycle,'points'); %#ok<AGROW>
                    fprintf('Diagnosis unavailable %.6f--%.6f: %s\n', ...
                        cycle.source_start_s,cycle.source_end_s,cycle.reason);
                    continue;
                end
                fprintf('%s | model %.6f s | cycle %.6f--%.6f | %d points -> real F4/NPU\n', ...
                    tag,stop,cycle.source_start_s,cycle.source_end_s,size(cycle.points,1));
                request=struct('op','cycle','case_id',case_id, ...
                    'source_start_s',cycle.source_start_s,'source_end_s',cycle.source_end_s, ...
                    'direction',cycle.direction,'points',cycle.points);
                reply=R4.rpc(request,config.rpc_timeout_s);
                decision=reply.decision;
                assert(strcmp(decision.case_id,case_id) ...
                    && abs(decision.source_end_s-cycle.source_end_s)<1e-9 ...
                    && strcmp(decision.decision_location,'board Linux'), ...
                    'Board decision context mismatch.');
                records{end+1}=struct('segment_stop_s',stop,'cycle',cycle, ...
                    'board',reply,'model_activation_s',activation); %#ok<AGROW>
                fprintf('  seq=%d NPU=%s streak=%d/%d ramp_request=%d\n', ...
                    decision.seq,decision.label,decision.streak,decision.required,decision.request_ramp_to_zero);
                if decision.newly_confirmed && isempty(first_alarm)
                    first_alarm=decision.alarm;
                end
                if enabled && decision.request_ramp_to_zero && isempty(activation)
                    % Never backdate the action to the cycle end: the whole chunk
                    % has already been simulated when the wall-time reply arrives.
                    activation=round(stop/config.sample_s)*config.sample_s+config.sample_s;
                    assert(activation+config.ramp_time_s<config.stop_time_s, ...
                        'Alarm arrived too late for a complete response observation.');
                    fprintf('  APPLY AT NEXT MODEL SAMPLE: %.9f s (not retrospectively).\n',activation);
                    R4.write(fullfile(output_dir,'action.json'),struct( ...
                        'case_id',case_id,'seq',decision.seq,'board_token',reply.token, ...
                        'source_cycle_end_s',cycle.source_end_s,'model_segment_stop_s',stop, ...
                        'model_activation_s',activation,'wall_elapsed_s',toc(wall), ...
                        'real_time',false,'hardware_motor_control',false));
                end
            end
            result=struct('case_id',case_id,'enabled',enabled,'data',data, ...
                'records',{records},'skipped_cycles',{skips},'first_alarm',first_alarm, ...
                'activation_s',activation,'wall_elapsed_s',toc(wall));
            results.(tag)=result;
            save(fullfile(output_dir,'partial_results.mat'),'results','config','status','-v7');
            draw_progress(figure_handle,results,config,tag);
        end
        assert(~isempty(records),'No valid electrical cycle reached the actual board.');
        status.cases_completed{end+1}=tag;
        R4.write(fullfile(output_dir,'status.json'),status);
    end
    status.stage='checking';R4.write(fullfile(output_dir,'status.json'),status);
    metrics=check_results(results,config);
    status.metrics=metrics;
    status.completed=true;
    status.passed=metrics.pre_action_match && metrics.reference_zero ...
        && metrics.tail_speed_pass && metrics.post_action_npu_cycles>0 ...
        && metrics.both_cases_have_confirmed_alarm;
    status.stage='completed';
    R4.write(fullfile(output_dir,'status.json'),status);
    save(fullfile(output_dir,'link_comparison.mat'),'results','config','status','-v7');
    R4.write(fullfile(output_dir,'evidence.json'),struct('status',status,'config',config,'results',results));
    draw_progress(figure_handle,results,config,'completed');
    saveas(figure_handle,fullfile(output_dir,'link_comparison.png'));
    fprintf('\nR4_FINISHED: passed=%d. Results: %s\n',status.passed,output_dir);
    if ~status.passed
        fprintf(2,'Execution finished but acceptance did not pass; do not claim a successful linkage.\n');
    end
catch exception
    status.stage='failed';status.failure_message=exception.message;
    R4.write(fullfile(output_dir,'status.json'),status);
    save(fullfile(output_dir,'partial_results.mat'),'results','config','status','-v7');
    fprintf(2,'R4 stopped; no success claimed. Partial results: %s\n',output_dir);
    rethrow(exception);
end
end

function metrics=check_results(results,config)
nf=results.no_feedback;fb=results.with_feedback;
assert(~isempty(fb.activation_s),'No live board decision triggered the model action.');
t=fb.data.RPM.time;pre=t<fb.activation_s;
metrics=struct();
metrics.pre_action_rpm_error=max(abs(fb.data.RPM.data(pre)-interp1(nf.data.RPM.time,nf.data.RPM.data,t(pre))));
metrics.pre_action_match=metrics.pre_action_rpm_error<1e-3;
cmd=fb.data.R4_AppliedCommand;mask=cmd.time>=fb.activation_s+config.ramp_time_s;
metrics.reference_zero=any(mask) && max(abs(cmd.data(mask)))<1e-4;
metrics.both_cases_have_confirmed_alarm=~isempty(nf.first_alarm) && ~isempty(fb.first_alarm);
metrics.post_action_npu_cycles=0;
for i=1:numel(fb.records)
    if fb.records{i}.cycle.source_start_s>=fb.activation_s
        metrics.post_action_npu_cycles=metrics.post_action_npu_cycles+1;
    end
end
tail=t>=config.stop_time_s-.1;
metrics.tail_feedback_abs_rpm=mean(abs(fb.data.RPM.data(tail)));
other=interp1(nf.data.RPM.time,nf.data.RPM.data,t(tail));
metrics.tail_no_feedback_abs_rpm=mean(abs(other));
metrics.tail_speed_pass=metrics.tail_no_feedback_abs_rpm>100 ...
    && metrics.tail_feedback_abs_rpm<=.2*metrics.tail_no_feedback_abs_rpm;
metrics.activation_s=fb.activation_s;
metrics.first_alarm_source_s=fb.first_alarm.source_time_s;
metrics.batch_causality_delay_model_s=fb.activation_s-fb.first_alarm.source_time_s;
metrics.note='All response times use model time. Wall-time waits are logged separately. No physical motor actuation.';
end

function draw_progress(h,results,config,tag)
if ~isgraphics(h),return;end
figure(h);clf(h);
colors={[.35 .4 .45],[.85 .22 .15]};names={'no_feedback','with_feedback'};
for i=1:2
    name=names{i};if ~isfield(results,name),continue;end
    r=results.(name);d=r.data;
    subplot(3,1,1);hold on;
    plot(d.R4_DiagnosticB.time,d.R4_DiagnosticB.data,'Color',colors{i});
    ylabel('B诊断电流 / A');grid on;xlim([0 config.stop_time_s]);
    subplot(3,1,2);hold on;
    plot(d.R4_AppliedCommand.time,d.R4_AppliedCommand.data,'Color',colors{i},'DisplayName',name);
    ylabel('转速参考 / rpm');grid on;xlim([0 config.stop_time_s]);legend('show','Interpreter','none');
    subplot(3,1,3);hold on;
    plot(d.RPM.time,d.RPM.data,'Color',colors{i},'DisplayName',name);
    ylabel('模型转速 / rpm');xlabel('模型时间 / s；板卡等待耗时不计入模型时间');grid on;
    xlim([0 config.stop_time_s]);legend('show','Interpreter','none');
    if ~isempty(r.activation_s)
        xline(r.activation_s,'--','本轮实板决策生效');
    end
end
sgtitle(['R4 非实时仿真联动 | ' tag ' | 实际电机未接入'],'Interpreter','none');drawnow;
end
