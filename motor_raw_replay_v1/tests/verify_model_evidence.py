import json,hashlib,math
from pathlib import Path
base=Path(__file__).resolve().parents[1]/'desktop/model_evidence'
m=json.loads((base/'manifest.json').read_text());p=base/'motor_bias_mlp17_logits_ZG.json';d=json.loads(p.read_text())
assert m['sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
ops=d['ops'];hard=[o for o in ops if o['_type_key'].endswith('::HardOp')]
assert len(hard)==11 and all(o['compile_target']=='@zhuget(330)' for o in hard)
assert sum(o['name'].endswith('Conv2dNode') for o in hard)==3
parsed=json.loads((base/'motor_bias_mlp17_parsed.json').read_text())
convs=[o for o in parsed['ops'] if o['_type_key'].endswith('::Conv2d')]
assert len(convs)==3
weights=sum(math.prod(o['inputs'][1]['dtype']['shape']) for o in convs)
bias=sum(math.prod(o['inputs'][2]['dtype']['shape']) for o in convs)
assert (weights,bias)==(560,49) and weights==m['logical_macs']
assert ops[-1]['inputs'][0]['dtype']['shape']==[1,17]
assert not any(o['_type_key'].endswith('::Softmax') for o in ops)
print('PASS: source hashes, ZG330 11 hardware nodes, 3 convolution nodes, 609 logical parameters, 17-logit output')
