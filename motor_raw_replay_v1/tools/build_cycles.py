"""Extract complete measured-angle cycles from the user's saved Simulink MAT.
Usage: python build_cycles.py motor_bias_raw.mat ../desktop/raw_cycles.json
Requires scipy and numpy only for regenerating the frozen replay data.
"""
import sys,json,hashlib,struct,binascii
from pathlib import Path
import numpy as np
from scipy.io import loadmat
source=Path(sys.argv[1]);dest=Path(sys.argv[2]);raw=loadmat(source,simplify_cells=True)['motor_data']
t=np.asarray(raw['theta']['time']);angle=np.unwrap(raw['theta']['data']);b=raw['ISensB']['data'];c=raw['ISensC']['data']
for name in ['ISensB','ISensC','RPM']:
 assert np.array_equal(raw[name]['time'],t),'unaligned source channel: '+name
cross=[]
for i in np.flatnonzero(np.diff(np.floor(angle/(2*np.pi)))!=0):
 direction=1 if angle[i+1]>angle[i] else -1
 boundary=(np.floor(angle[i]/(2*np.pi))+(1 if direction>0 else 0))*2*np.pi
 frac=(boundary-angle[i])/(angle[i+1]-angle[i]);cross.append((float(t[i]+frac*(t[i+1]-t[i])),direction,float(boundary)))
candidates=[]
for start,end in zip(cross,cross[1:]):
 t0,sign,a0=start;t1,_,a1=end
 if start[1]!=end[1] or not (.9<t0 and t1<1.3):continue
 tt=np.r_[t0,t[(t>t0)&(t<t1)],t1];aa=np.interp(tt,t,angle);aa[0]=a0;aa[-1]=a1
 if np.any(np.diff(aa)*sign<=0):continue
 middle=float(np.interp(np.pi,sign*(aa-a0),tt))
 f1=.5/(middle-t0);f2=.5/(t1-middle);variation=abs(f1-f2)/((f1+f2)/2)
 bb=np.interp(tt,t,b);cc=np.interp(tt,t,c)
 mean=[float(np.trapezoid(v,tt)/(t1-t0)) for v in (bb,cc)]
 if 1/(t1-t0)<10 or variation>.05 or max(abs(x) for x in mean)>.005:continue
 candidates.append((tt,bb,cc,aa-a0,variation,float(np.mean(np.interp(tt,t,raw['RPM']['data'])))))
labels=['Normal']+[f'{phase}_{bias:+.1f}A' for phase in ['B','C'] for bias in [.1,.2,.5,1.,-.1,-.2,-.5,-1.]]
assert len(candidates)>=len(labels)
cycles=[]
for idx,label in enumerate(labels):
 tt,bb,cc,aa,var,rpm=candidates[idx]
 if label!='Normal':
  phase,value=label.split('_');bias=float(value[:-1]);bb=bb+(bias if phase=='B' else 0);cc=cc+(bias if phase=='C' else 0)
 points=np.column_stack([(tt-tt[0]).astype('float32'),bb.astype('float32'),cc.astype('float32'),aa.astype('float32')])
 # Gold is based on exactly the binary32 samples transmitted to the MCU.
 v=points.astype('float64');means=[float(np.trapezoid(v[:,j],v[:,0])/v[-1,0]) for j in (1,2)]
 cycles.append(dict(id=idx+1,label=label,source_start_s=float(tt[0]),source_end_s=float(tt[-1]),electrical_hz=1/float(tt[-1]-tt[0]),half_cycle_frequency_variation=var,rpm=rpm,points=points.tolist(),golden_mean=means))
result=dict(version='raw_cycle_v1',source_name=source.name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),source_signal_names=['theta','ISensB','ISensC','RPM'],selection_interval_s=[.9,1.3],note='Original Simulink samples with angle-boundary interpolation; controlled constant offsets added offline to diagnostic channels. Not new independent motor experiments.',cycle_segmentation='PC: unwrap electrical angle, interpolate full 2pi boundaries; F4: time-weighted trapezoidal integration of supplied endpoints',cycles=cycles)
dest.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print('Saved',len(cycles),'complete cycles;',len(cycles[0]['points']),'points in first cycle; max baseline/offset errors',max(abs(x['golden_mean'][0]-(float(x['label'].split('_')[1][:-1]) if x['label'].startswith('B_') else 0)) for x in cycles))
