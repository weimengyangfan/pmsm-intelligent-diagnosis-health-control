function test_r4_algorithms()
% Pure synthetic SOFTWARE test; no actual motor, F4, FPGA or NPU.
t=(0:25e-6:.1).';angle=mod(2*pi*100*t+.3,2*pi);
data=struct('theta',struct('time',t,'data',angle), ...
    'R4_DiagnosticB',struct('time',t,'data',sin(2*pi*100*t+.3)+.2), ...
    'R4_DiagnosticC',struct('time',t,'data',cos(2*pi*100*t+.3)));
config=struct('warmup_s',0,'max_half_cycle_variation',.25);
[cycles,cursor,skipped]=R4.cycles(data,0,config);
assert(numel(cycles)>=8 && skipped==0);
for i=1:numel(cycles)
    p=cycles(i).points;
    assert(cycles(i).quality && cycles(i).direction==1);
    means=trapz(p(:,1),p(:,2:3))/p(end,1);
    assert(max(abs(means-[.2 0]))<1e-4);
end
[again,~,~]=R4.cycles(data,cursor,config);assert(isempty(again));
data.theta.data=mod(-2*pi*100*t+.3,2*pi);
[reverse,~,skipped]=R4.cycles(data,0,config);
assert(skipped==0 && all([reverse.direction]==-1));
fprintf('R4_ALGORITHM_SOFTWARE_PASS (synthetic inputs only).\n');
end
