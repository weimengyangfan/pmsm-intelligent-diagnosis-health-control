"""Session summary treats negative protection checks separately from classification."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from dashboard import summarize
rows=[dict(negative_test=False,state='result',correct=True,packet={'npu':{'top_tied':False}},npu_forward_read_ms=.5,pc_roundtrip_ms=3400),dict(negative_test=True,state='crc_reject',correct=False,packet=None),dict(negative_test=False,state='timeout',correct=False,packet=None)]
s=summarize(rows)
assert (s['requests'],s['valid'],s['correct'],s['invalid'],s['negative'],s['rejected'])==(2,1,1,1,1,1)
assert s['npu']==.5 and s['trip']==3400
rows[0]['packet']['npu']['top_tied']=True
assert summarize(rows)['valid']==0 and summarize(rows)['npu'] is None
print('PASS: negative CRC excluded from classification; timeout and top tie invalid; measured timing only')
