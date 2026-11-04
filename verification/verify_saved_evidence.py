import gzip, importlib.util, json, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'motor_link_r4/board'))
spec=importlib.util.spec_from_file_location('saved_audit',root/'verification/audit_run.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
source=root/'evidence/R4_20261103_121043_90579/evidence.json.gz'
result=module.audit(json.loads(gzip.decompress(source.read_bytes())))
print(json.dumps(result,ensure_ascii=False,indent=2))
