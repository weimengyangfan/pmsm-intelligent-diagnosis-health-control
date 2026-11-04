"""Subprocess integration against an explicitly FAKE child service, no hardware."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from test_contracts import arm, packet, ROOT


class Wrapper(unittest.TestCase):
    def test_control_stream_and_real_child_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('motor_link_service_r4.py','r4_policy.py'):
                shutil.copy2(ROOT/'board'/name,root/name)
            (root/'motor_monitor_service.py').write_text('''
import json,time
from pathlib import Path
print('EVENT '+json.dumps(dict(event='ready')),flush=True)
p=Path('fixture.jsonl');count=0
while True:
 if p.exists():
  lines=p.read_text().splitlines()
  for line in lines[count:]:print('EVENT '+line,flush=True)
  count=len(lines)
 time.sleep(.01)
''')
            proc=subprocess.Popen([sys.executable,'-u',str(root/'motor_link_service_r4.py')],
                                  stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            buffer=b''
            def receive(event):
                nonlocal buffer
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if b'\n' not in buffer:
                        ready,_,_=select.select([proc.stdout],[],[],.2)
                        if ready:buffer+=os.read(proc.stdout.fileno(),65536)
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        if line.startswith(b'R4_EVENT '):
                            item=json.loads(line[9:])
                            if item['event']==event:return item
                self.fail('Wrapper did not emit '+event)
            def command(op,token,**fields):
                proc.stdin.write((json.dumps(dict(op=op,token=token,**fields))+'\n').encode());proc.stdin.flush()
            try:
                receive('ready');command('reset','reset',case_id='test');receive('reset')
                a=arm(1)
                command('arm','a1',arm=a);receive('armed')
                with (root/'fixture.jsonl').open('a') as f:f.write(json.dumps(dict(event='result',packet=packet(2,'Normal')))+'\n')
                receive('ignored')
                with (root/'fixture.jsonl').open('a') as f:f.write(json.dumps(dict(event='result',packet=packet(1,'B_+0.2A')))+'\n')
                decision=receive('decision');self.assertEqual(decision['token'],'a1')
                self.assertEqual(decision['decision']['streak'],1)
                command('arm','duplicate',arm=a)
                self.assertIn('repeated',receive('error')['reason'])
                command('shutdown','bye');proc.wait(timeout=5)
                self.assertEqual(proc.returncode,0)
            finally:
                if proc.poll() is None:proc.terminate();proc.wait(timeout=5)
                proc.stdin.close();proc.stdout.close()


if __name__=='__main__':unittest.main()
