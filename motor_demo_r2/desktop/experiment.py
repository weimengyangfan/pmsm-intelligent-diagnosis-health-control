"""Deterministic monitoring rules. Expected labels NEVER drive these rules."""
import math
LABELS=['Normal']+[f'{p}_{b:+.1f}A' for p in ('B','C') for b in (.1,.2,.5,1.,-.1,-.2,-.5,-1.)]
CENTERS=[(0.,0.)]+[(b if p=='B' else 0.,b if p=='C' else 0.) for p in ('B','C') for b in (.1,.2,.5,1.,-.1,-.2,-.5,-1.)]

def nearest_center(b,c):
    if not all(math.isfinite(x) for x in (b,c)):return None
    distances=[(b-x)**2+(c-y)**2 for x,y in CENTERS]
    order=sorted(range(len(distances)),key=distances.__getitem__)
    if abs(distances[order[0]]-distances[order[1]])<1e-12:return None
    return LABELS[order[0]]

def fault_group(label):
    if label not in LABELS:raise ValueError('unsupported class')
    return None if label=='Normal' else label[0]+label[2]

class Confirmation:
    def __init__(self,count=3):
        if count<1:raise ValueError('confirmation count must be positive')
        self.required=count;self.last_index=None;self.last_end=None
        self.alarm=None;self.candidate=None;self.count=0;self.normal=0
    def step(self,label,index,t0,t1,valid=True):
        contiguous=self.last_index is None or (index==self.last_index+1 and abs(t0-self.last_end)<1e-7)
        self.last_index=index;self.last_end=t1
        transition=None
        if not valid or label not in LABELS or not contiguous or t1<=t0:
            self.candidate=None;self.count=self.normal=0;status='invalid'
        elif label=='Normal':
            self.candidate=None;self.count=0;self.normal+=1
            if self.alarm and self.normal>=self.required:self.alarm=None;transition='recovered'
            status='recovering' if self.alarm else 'normal'
        else:
            self.normal=0;group=fault_group(label)
            self.count=self.count+1 if group==self.candidate else 1;self.candidate=group
            if self.count>=self.required and self.alarm!=group:self.alarm=group;transition='alarm'
            status='alarm' if self.alarm else 'pending'
        return dict(status=status,alarm_active=bool(self.alarm),alarm_group=self.alarm,candidate=self.candidate,abnormal_count=self.count,normal_count=self.normal,transition=transition,cycle_index=index,sim_start_s=t0,sim_end_s=t1,contiguous=contiguous)

def valid_result(packet):
    try:
        if not isinstance(packet,dict):return False
        n=packet.get('npu',{});s=n.get('scores',[]);label=n.get('label');received=packet.get('received',[])
        if label not in LABELS or n.get('top_tied') is not False or len(s)!=17 or not all(math.isfinite(x) for x in s):return False
        if len(received)!=2 or not all(math.isfinite(x) for x in received):return False
        peak=max(range(17),key=s.__getitem__)
        return s.count(s[peak])==1 and LABELS[peak]==label and n.get('class_index_1based')==peak+1
    except (TypeError,ValueError,AttributeError):return False

def result_summary(results):
    valid=[r for r in results if r.get('state')=='result' and valid_result(r.get('packet'))]
    npu=sum(r['predicted']==r['expected'] for r in valid)
    baseline=sum(r.get('baseline_prediction')==r['expected'] for r in valid)
    groups={}
    for r in valid:
        level=str(r.get('perturbation_A',0.))
        g=groups.setdefault(level,dict(count=0,npu_correct=0,baseline_correct=0));g['count']+=1;g['npu_correct']+=r['predicted']==r['expected'];g['baseline_correct']+=r.get('baseline_prediction')==r['expected']
    return dict(total=len(results),valid=len(valid),invalid=len(results)-len(valid),npu_correct=npu,baseline_correct=baseline,npu_accuracy=npu/len(valid) if valid else None,baseline_accuracy=baseline/len(valid) if valid else None,by_perturbation=groups,instant_alarm_events=sum(r.get('instant_rule',{}).get('transition')=='alarm' for r in results),confirmed_alarm_events=sum(r.get('confirmed_rule',{}).get('transition')=='alarm' for r in results),confirmed_recovery_events=sum(r.get('confirmed_rule',{}).get('transition')=='recovered' for r in results),transient_instant_alarms=sum(r.get('phase')=='短暂偏移' and r.get('instant_rule',{}).get('transition')=='alarm' for r in results),transient_confirmed_alarms=sum(r.get('phase')=='短暂偏移' and r.get('confirmed_rule',{}).get('transition')=='alarm' for r in results))
