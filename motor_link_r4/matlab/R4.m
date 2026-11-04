classdef R4
% Shared helpers. Only model copies and R4's own files are written.
methods(Static)
function root=root()
root=fileparts(fileparts(mfilename('fullpath')));
end
function write(path,value)
folder=fileparts(path);if ~isfolder(folder),mkdir(folder);end
temp=[path '.' char(java.util.UUID.randomUUID) '.tmp'];
fid=fopen(temp,'w','n','UTF-8');assert(fid>=0,'Cannot write output file.');
cleanup=onCleanup(@()fclose(fid)); %#ok<NASGU>
fprintf(fid,'%s',jsonencode(value));clear cleanup;
[ok,msg]=movefile(temp,path,'f');assert(ok,msg);
end
function value=read(path)
value=jsondecode(fileread(path));
end
function hash=sha(path)
fid=fopen(path,'rb');assert(fid>=0,'Cannot hash file.');
cleanup=onCleanup(@()fclose(fid)); %#ok<NASGU>
digest=java.security.MessageDigest.getInstance('SHA-256');
while ~feof(fid)
    bytes=fread(fid,1024*1024,'*uint8');digest.update(typecast(bytes,'int8'));
end
hash=lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2).',1,[]));
end
function config=config()
path=fullfile(R4.root,'settings.json');
assert(isfile(path),'Run prepare_motor_link_r4 first.');
config=R4.read(path);
assert(strcmp(config.version,'R4.0.0'),'Configuration version mismatch.');
assert(strcmp(R4.sha(config.prepared_model),config.prepared_model_sha256), ...
    'Prepared model changed. Run prepare_motor_link_r4 and check_motor_link_r4 again.');
assert(strcmp(R4.sha(config.source_model),config.source_model_sha256), ...
    'Source model changed since preparation. Prepare and check again.');
end
function gate=gate(config,activation)
if isempty(activation)
    gate=[0 1;config.stop_time_s 1];
else
    assert(activation>0 && activation+config.ramp_time_s<config.stop_time_s, ...
        'Not enough simulation time to apply the ramp.');
    gate=[0 1;activation 1;activation+config.ramp_time_s 0;config.stop_time_s 0];
end
end
function instrument(model,config)
foc=[model '/FOC'];controller=[foc '/FOC_CURRENT'];
assert(getSimulinkBlockHandle(controller)>0,'FOC/FOC_CURRENT not found.');
assert(getSimulinkBlockHandle([foc '/R3_CommandProduct'])<0, ...
    'Select the original zero-bias model, not an R3 result copy.');
assert(getSimulinkBlockHandle([foc '/R4_CommandProduct'])<0, ...
    'Select the original model, not an R4 prepared copy.');
ports=find_system(controller,'SearchDepth',1,'BlockType','Inport','Port','5');
assert(numel(ports)==1 && strcmp(get_param(ports{1},'Name'),'CMD_RPM'), ...
    'Controller input 5 is not CMD_RPM.');
outer=get_param(controller,'PortHandles');line=get_param(outer.Inport(5),'Line');
conversion=get_param(line,'SrcBlockHandle');
assert(strcmp(get_param(conversion,'BlockType'),'DataTypeConversion'), ...
    'Expected command Data Type Conversion upstream.');
cp=get_param(conversion,'PortHandles');line=get_param(cp.Inport(1),'Line');
src=get_param(line,'SrcPortHandle');assert(src>0,'Command source missing.');
mw=get_param(model,'ModelWorkspace');
assert(strcmpi(mw.DataSource,'Model File'),'Model Workspace must use Model File.');
assignin(mw,'BiasB',0);assignin(mw,'BiasC',0);
assignin(mw,'R4_BiasB',[0 0;config.fault_time_s config.bias_B_A;config.stop_time_s config.bias_B_A]);
assignin(mw,'R4_BiasC',[0 0;config.stop_time_s 0]);
assignin(mw,'R4_CommandScale',R4.gate(config,[]));
position=get_param(conversion,'Position');x=position(1);y=mean(position([2 4]));
product=[foc '/R4_CommandProduct'];
add_block('simulink/Math Operations/Product',product,'Inputs','2', ...
    'Position',[x-95 y-25 x-55 y+25]);
scale=[foc '/R4_CommandScaleSource'];
R4.source(scale,'R4_CommandScale','on',[300 900 480 930]);
delete_line(foc,src,cp.Inport(1));
pp=get_param(product,'PortHandles');sp=get_param(scale,'PortHandles');
add_line(foc,src,pp.Inport(1),'autorouting','on');
add_line(foc,sp.Outport(1),pp.Inport(2),'autorouting','on');
add_line(foc,pp.Outport(1),cp.Inport(1),'autorouting','on');
R4.log(sp.Outport(1),'R4_CommandScale');
R4.probe(foc,src,'R4_BaseCommand',[600 900 650 930]);
R4.probe(foc,cp.Outport(1),'R4_AppliedCommand',[800 900 850 930]);
for phase={'B','C'}
    ch=phase{1};raw=[foc '/I_' ch];
    assert(getSimulinkBlockHandle(raw)>0,'Raw current inport missing.');
    rp=get_param(raw,'PortHandles');
    if ch=='B',row=1020;else,row=1150;end
    bias=[foc '/R4_Bias' ch 'Source'];
    R4.source(bias,['R4_Bias' ch],'off',[300 row 480 row+30]);
    sum_block=[foc '/R4_Diagnostic' ch];
    add_block('simulink/Math Operations/Sum',sum_block,'Inputs','++', ...
        'Position',[600 row 635 row+35]);
    ps=get_param(sum_block,'PortHandles');bp=get_param(bias,'PortHandles');
    add_line(foc,rp.Outport(1),ps.Inport(1),'autorouting','on');
    add_line(foc,bp.Outport(1),ps.Inport(2),'autorouting','on');
    R4.terminate(foc,ps.Outport(1),['R4_Diagnostic' ch 'End'],[750 row 770 row+20]);
    R4.log(ps.Outport(1),['R4_Diagnostic' ch]);R4.log(bp.Outport(1),['R4_Bias' ch]);
    R4.probe(foc,rp.Outport(1),['R4_Raw' ch],[900 row 950 row+30]);
end
set_param(model,'SimulationMode','normal','StartTime','0', ...
    'StopTime',num2str(config.stop_time_s,17),'LoadInitialState','off', ...
    'SaveFinalState','on','SaveOperatingPoint','on','FinalStateName','R4FinalState', ...
    'SignalLogging','on','SignalLoggingName','logsout','SignalLoggingSaveFormat','Dataset', ...
    'ReturnWorkspaceOutputs','on');
end
function source(path,variable,interpolation,position)
add_block('simulink/Sources/From Workspace',path,'VariableName',variable, ...
    'SampleTime','0','ZeroCross','off','Position',position);
set_param(path,'OutputAfterFinalValue','Holding final value');
set_param(path,'Interpolate',interpolation);
assert(strcmpi(get_param(path,'OutputAfterFinalValue'),'Holding final value'), ...
    'From Workspace final-value policy was not retained.');
end
function log(port,name)
set_param(port,'DataLogging','on','DataLoggingNameMode','Custom','DataLoggingName',name);
end
function probe(parent,source,name,position)
path=[parent '/' name 'Probe'];
add_block('simulink/Math Operations/Gain',path,'Gain','1','Position',position);
p=get_param(path,'PortHandles');add_line(parent,source,p.Inport(1),'autorouting','on');
R4.terminate(parent,p.Outport(1),[name 'End'],position+[100 0 70 -10]);
R4.log(p.Outport(1),name);
end
function terminate(parent,source,name,position)
path=[parent '/' name];add_block('simulink/Sinks/Terminator',path,'Position',position);
p=get_param(path,'PortHandles');add_line(parent,source,p.Inport(1),'autorouting','on');
end
function [data,op]=step(model,stop_time,initial,gate)
mw=get_param(model,'ModelWorkspace');assignin(mw,'R4_CommandScale',gate);
input=Simulink.SimulationInput(model);
input=input.setModelParameter('StopTime',num2str(stop_time,17), ...
    'SimulationMode','normal','SaveFinalState','on','SaveOperatingPoint','on', ...
    'FinalStateName','R4FinalState','ReturnWorkspaceOutputs','on');
if isempty(initial)
    input=input.setModelParameter('LoadInitialState','off');previous=0;
else
    assert(isa(initial,'Simulink.op.ModelOperatingPoint'),'Complete model operating point required.');
    previous=initial.snapshotTime;
    assert(stop_time>previous,'Continuation time must increase.');
    input=input.setInitialState(initial);
    % Keep original StartTime=0; snapshotTime supplies the continuation instant.
end
output=sim(input);op=output.get('R4FinalState');
assert(isa(op,'Simulink.op.ModelOperatingPoint'),'Model did not save a complete operating point.');
assert(abs(op.snapshotTime-stop_time)<1e-8,'Simulation stopped early.');
data=R4.extract(output.get('logsout'));
assert(data.RPM.time(1)>=previous-1e-8 && data.RPM.time(end)>=stop_time-1e-8, ...
    'Continuation log interval is invalid.');
end
function data=extract(dataset)
names={'RPM','theta','R4_RawB','R4_RawC','R4_DiagnosticB','R4_DiagnosticC', ...
    'R4_BiasB','R4_BiasC','R4_BaseCommand','R4_AppliedCommand','R4_CommandScale'};
all_names=dataset.getElementNames;data=struct();
for i=1:numel(names)
    name=names{i};assert(sum(strcmp(all_names,name))==1, ...
        ['Missing or duplicate log signal: ' name '. Enable signal logging in the original model first.']);
    element=dataset.getElement(name);v=element.Values;
    t=double(v.Time(:));y=double(v.Data(:));
    assert(numel(t)==numel(y) && ~isempty(t) && all(diff(t)>0) ...
        && all(isfinite(t)) && all(isfinite(y)),['Invalid scalar log: ' name]);
    data.(name)=struct('time',t,'data',y);
end
end
function all=append(all,data)
if isempty(fieldnames(all)),all=data;return;end
names=fieldnames(data);
for i=1:numel(names)
    n=names{i};keep=data.(n).time>all.(n).time(end)+1e-10;
    all.(n).time=[all.(n).time;data.(n).time(keep)];
    all.(n).data=[all.(n).data;data.(n).data(keep)];
end
end
function metrics=compare(a,b)
metrics=struct();names=fieldnames(a);
for i=1:numel(names)
    n=names{i};t=a.(n).time;
    v=interp1(b.(n).time,b.(n).data,t,'linear');
    assert(all(isfinite(v)),['Missing continuation samples: ' n]);
    metrics.(n)=max(abs(v-a.(n).data));
end
end
function response=rpc(request,timeout)
runtime=fullfile(R4.root,'runtime');state=R4.read(fullfile(runtime,'bridge.json'));
assert(state.ready,'Start start_bridge.cmd and wait for R4_BRIDGE_READY.');
id=strrep(char(java.util.UUID.randomUUID),'-','');
request.id=id;request.bridge_session=state.bridge_session;
destination=fullfile(runtime,'outbox',[id '.json']);
R4.write(fullfile(runtime,'inbox',[id '.json']),request);
clock=tic;
while ~isfile(destination)
    pause(.05);drawnow;
    assert(toc(clock)<timeout, ...
        'Bridge request timed out. Stop this bridge before restarting; do not reuse an uncertain request.');
end
reply=R4.read(destination);
assert(strcmp(reply.id,id) && strcmp(reply.bridge_session,state.bridge_session),'RPC identity mismatch.');
assert(reply.ok,['Bridge rejected request: ' R4.error_text(reply)]);
response=reply.result;
end
function text=error_text(reply)
if isfield(reply,'error'),text=reply.error;else,text='unknown error';end
end
function [cycles,cursor,skipped]=cycles(data,cursor,config)
% PC segmentation remains explicit: full electrical-angle cycles, interpolated endpoints.
t=data.theta.time;angle=unwrap(data.theta.data);
assert(max(abs(diff(angle)))<pi,'Electrical angle contains an ambiguous jump.');
cross_t=[];cross_a=[];cross_d=[];
indices=find(diff(floor(angle/(2*pi)))~=0);
for j=indices(:).'
    direction=sign(angle(j+1)-angle(j));
    boundary=(floor(angle(j)/(2*pi))+(direction>0))*2*pi;
    fraction=(boundary-angle(j))/(angle(j+1)-angle(j));
    cross_t(end+1)=t(j)+fraction*(t(j+1)-t(j)); %#ok<AGROW>
    cross_a(end+1)=boundary;cross_d(end+1)=direction; %#ok<AGROW>
end
cycles=struct('source_start_s',{},'source_end_s',{},'direction',{}, ...
    'points',{},'quality',{},'reason',{});skipped=0;
for i=1:numel(cross_t)-1
    t0=cross_t(i);t1=cross_t(i+1);
    if t1<=cursor+1e-9 || t0<config.warmup_s,continue;end
    cursor=t1;direction=cross_d(i);reason='';variation=NaN;
    tt=[t0;t(t>t0 & t<t1);t1];aa=interp1(t,angle,tt);
    aa(1)=cross_a(i);aa(end)=cross_a(i+1);
    if direction~=cross_d(i+1) || abs(cross_a(i+1)-cross_a(i))<2*pi-1e-7 ...
            || any(diff(aa)*direction<=0)
        reason='incomplete/nonmonotonic electrical cycle';
    elseif t1-t0>.100001 || numel(tt)>4096 || numel(tt)<3
        reason='cycle outside existing MCU duration/point limits';
    else
        middle=interp1(direction*(aa-aa(1)),tt,pi);
        f1=.5/(middle-t0);f2=.5/(t1-middle);
        variation=abs(f1-f2)/((f1+f2)/2);
        if ~isfinite(variation) || variation>config.max_half_cycle_variation
            reason='cycle frequency changes too quickly';
        end
    end
    points=[];
    if isempty(reason)
        b=interp1(data.R4_DiagnosticB.time,data.R4_DiagnosticB.data,tt);
        c=interp1(data.R4_DiagnosticC.time,data.R4_DiagnosticC.data,tt);
        points=double(single([tt-t0 b c]));
        if ~all(isfinite(points(:))) || any(diff(points(:,1))<=0)
            reason='invalid binary32 sample data';
        end
    end
    quality=isempty(reason);skipped=skipped+~quality;
    cycles(end+1)=struct('source_start_s',t0,'source_end_s',t1, ...
        'direction',direction,'points',points,'quality',quality,'reason',reason); %#ok<AGROW>
end
end
end
end
