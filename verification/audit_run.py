"""Independent offline audit of R4 evidence.json. Does not execute a model/NPU.
Usage: python tools/audit_run.py path/to/evidence.json
Requires numpy. The full saved source curves are checked against transmitted points.
"""
import json
from pathlib import Path
import struct
import sys

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'))
from r4_policy import Policy


def audit(evidence):
    c=evidence['config'];results=evidence['results'];report={}
    for case in ('no_feedback','with_feedback'):
        r=results[case];p=Policy();p.reset(r['case_id']);max_error=0.;post=0
        for row in r['records']:
            cycle=row['cycle'];board=row['board'];packet=board['packet'];points=np.array(cycle['points'],dtype=np.float64)
            assert points.ndim==2 and points.shape[1]==3 and len(points)>=3
            assert np.array_equal(points,points.astype(np.float32).astype(np.float64))
            assert np.isfinite(points).all() and points[0,0]==0 and np.all(np.diff(points[:,0])>0)
            source_time=cycle['source_start_s']+points[:,0]
            assert abs(source_time[-1]-cycle['source_end_s'])<1e-7
            for column,ch in [(1,'B'),(2,'C')]:
                s=r['data']['R4_Diagnostic'+ch]
                target=np.interp(source_time,s['time'],s['data'])
                err=float(np.max(np.abs(target-points[:,column])))
                max_error=max(max_error,err)
                assert err<2e-4,'Transferred samples do not match this run\'s simulated current'
            golden=[]
            for col in (1,2):
                area=0.
                for prev,cur in zip(points,points[1:]):
                    area+=.5*(prev[col]+cur[col])*(cur[0]-prev[0])
                golden.append(float(np.float32(area/points[-1,0])))
            assert max(abs(x-y) for x,y in zip(golden,board['mcu_mean']))<=2e-6
            arm=dict(case_id=r['case_id'],seq=packet['seq'],
                     mean_hex=[struct.pack('<f',v).hex() for v in board['mcu_mean']],
                     source_start_s=cycle['source_start_s'],source_end_s=cycle['source_end_s'],direction=cycle['direction'])
            decision=p.accept(arm,packet)
            recorded=dict(board['decision'])
            # MATLAB jsondecode/jsonencode round-trip maps JSON null to [].
            # Normalize ONLY an absent pre-alarm value; keep all decisions exact.
            if recorded.get('alarm')==[]:
                recorded['alarm']=None
            assert decision==recorded,'Board confirmation history differs from the accepted NPU packets'
            assert cycle['source_end_s']<=row['segment_stop_s']+1e-8
            activation=r['activation_s']
            if isinstance(activation,(int,float)) and cycle['source_start_s']>=activation:
                post+=1
        report[case]=dict(npu_cycles=len(r['records']),source_sample_error_A=max_error,
                          post_action_npu_cycles=post,confirmed_alarm=p.alarm)
    fb=results['with_feedback'];nf=results['no_feedback'];activation=fb['activation_s']
    assert isinstance(activation,(int,float)) and fb['first_alarm']
    triggering=[x for x in fb['records'] if x['board']['decision']['newly_confirmed']]
    assert len(triggering)==1
    assert abs(activation-triggering[0]['segment_stop_s']-c['sample_s'])<1e-8
    assert report['with_feedback']['post_action_npu_cycles']>0
    t=np.array(fb['data']['RPM']['time']);y=np.array(fb['data']['RPM']['data'])
    other=np.interp(t,nf['data']['RPM']['time'],nf['data']['RPM']['data'])
    pre=t<activation
    assert np.max(np.abs(y[pre]-other[pre]))<1e-3
    tail=t>=c['stop_time_s']-.1
    assert np.mean(np.abs(other[tail]))>100
    assert np.mean(np.abs(y[tail]))<=.2*np.mean(np.abs(other[tail]))
    command=fb['data']['R4_AppliedCommand'];mask=np.array(command['time'])>=activation+c['ramp_time_s']
    assert mask.any() and np.max(np.abs(np.array(command['data'])[mask]))<1e-4
    assert evidence['status']['completed'] and evidence['status']['passed']
    return dict(passed=True,real_time=False,hardware_motor_control=False,cases=report,
                note='Offline consistency audit of uploaded evidence, not independent physical authentication.')


if __name__=='__main__':
    source=Path(sys.argv[1]);result=audit(json.loads(source.read_text(encoding='utf-8-sig')))
    output=source.with_name('independent_audit.json')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
