"""Pure software checks; generated score fixtures are NOT hardware evidence."""
import copy,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from experiment import LABELS,CENTERS,Confirmation,nearest_center,valid_result,result_summary
from reporting import report_html,feedback_requests,json_safe

def fixture(label,seq=1):
    scores=[-4.]*17;scores[LABELS.index(label)]=7.
    return dict(seq=seq,received=[0.,0.],npu=dict(label=label,scores=scores,top_tied=False,class_index_1based=LABELS.index(label)+1,forward_read_ms=None))

def verify():
    path=Path(__file__).resolve().parents[1]/'desktop/scenarios.json'
    data=json.loads(path.read_text(encoding='utf-8'));continuous=data['continuous']
    assert [len(data[k]) for k in ('continuous','coverage','perturbed')]==[21,17,51]
    for left,right in zip(continuous,continuous[1:]):
        assert abs(left['source_end_s']-right['source_start_s'])<1e-12
        assert right['stream_index']==left['stream_index']+1
    for cycle in data['continuous']+data['coverage']+data['perturbed']:
        points=cycle['points'];duration=points[-1][0]
        assert points[0][0]==0 and all(b[0]>a[0] for a,b in zip(points,points[1:]))
        assert all(math.isfinite(v) for p in points for v in p)
        assert abs(abs(points[-1][3])-2*math.pi)<1e-6
        gold=[sum((a[j]+b[j])*.5*(b[0]-a[0]) for a,b in zip(points,points[1:]))/duration for j in (1,2)]
        assert max(abs(a-b) for a,b in zip(gold,cycle['golden_mean']))<1e-12
        assert all(abs(x)<=cycle['perturbation_A']+1e-12 for x in cycle['perturbation_delta_A'])
    for label,center in zip(LABELS,CENTERS):assert nearest_center(*center)==label
    assert nearest_center(.05,0) is None and nearest_center(float('nan'),0) is None
    normal=fixture('Normal');assert valid_result(normal)
    for mutation in ['tie','nan','unknown','missing','false_index','nonfinite_input']:
        p=copy.deepcopy(normal)
        if mutation=='tie':p['npu']['scores'][1]=7.
        if mutation=='nan':p['npu']['scores'][2]=float('nan')
        if mutation=='unknown':p['npu']['label']='not a class'
        if mutation=='missing':del p['npu']['top_tied']
        if mutation=='false_index':p['npu']['class_index_1based']=2
        if mutation=='nonfinite_input':p['received'][0]=float('inf')
        assert not valid_result(p),mutation
    one=Confirmation(1);three=Confirmation(3);rows=[]
    for i,c in enumerate(continuous):
        p=fixture(c['label'],i)
        rows.append(dict(seq=i,packet=p,state='result',expected=c['label'],predicted=c['label'],phase=c['phase'],baseline_prediction=nearest_center(*c['golden_mean']),raw_cycle_end_s=c['source_end_s'],instant_rule=one.step(p['npu']['label'],i,c['source_start_s'],c['source_end_s']),confirmed_rule=three.step(p['npu']['label'],i,c['source_start_s'],c['source_end_s'])))
    s=result_summary(rows)
    assert (s['valid'],s['instant_alarm_events'],s['confirmed_alarm_events'],s['confirmed_recovery_events'],s['transient_instant_alarms'],s['transient_confirmed_alarms'])==(21,3,2,2,1,0)
    assert [i+1 for i,r in enumerate(rows) if r['confirmed_rule']['transition']=='alarm']==[10,17]
    assert [i+1 for i,r in enumerate(rows) if r['confirmed_rule']['transition']=='recovered']==[14,21]
    # The rule has no expected-label parameter. Relabeling the report cannot change it.
    other=copy.deepcopy(rows)
    for r in other:r['expected']='C_+1.0A'
    assert [r['confirmed_rule'] for r in other]==[r['confirmed_rule'] for r in rows]
    assert result_summary(other)['npu_correct']!=s['npu_correct']
    policy=Confirmation(3)
    for i,label in enumerate(['B_+0.1A','B_+0.2A','B_+0.5A']):r=policy.step(label,i,i,i+1)
    assert r['alarm_active'] and r['transition']=='alarm'
    r=policy.step(None,3,3,4,False);assert r['alarm_active'] and r['status']=='invalid'
    for i in range(4,6):assert policy.step('Normal',i,i,i+1)['alarm_active']
    assert not policy.step('Normal',6,6,7)['alarm_active']
    policy=Confirmation(3)
    assert policy.step('B_+0.1A',0,0,1)['abnormal_count']==1
    assert policy.step('B_-0.1A',1,1,2)['abnormal_count']==1
    assert policy.step('B_-0.1A',3,3,4)['status']=='invalid'
    assert policy.step('B_-0.1A',4,4,5)['abnormal_count']==1
    bundle=dict(provenance=dict(test_fixture_only=True),runs=[dict(id='fixture',mode='continuous',name='unit test <script>',status='completed',planned_count=21,results=rows)])
    requests=feedback_requests(bundle)['requests'];assert len(requests)==2 and all(r['executed'] is False for r in requests)
    rendered=report_html(bundle);assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    bad=json_safe({'record':[float('nan'),float('inf'),float('-inf')]})
    assert bad['record'][0]=={'invalid_numeric_value':'nan'}
    json.dumps(bad,allow_nan=False)
    invalid=dict(state='timeout',packet=None,expected='Normal',predicted=None)
    assert result_summary(rows+[invalid])['invalid']==1
    print('PASS: 89 frozen windows, exact FP32 golden integration, 21-window continuity, honest baseline, invalid outputs, transient/latched/recovery policy, report and unexecuted feedback requests')

if __name__=='__main__':verify()
