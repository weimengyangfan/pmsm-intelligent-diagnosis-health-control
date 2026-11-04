"""No hardware required: connection failure, fragmented SSH, timeout, cancellation."""
import sys,types,queue
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import monitor
class V:
 def __init__(self,x=''):self.x=x
 def get(self):return self.x
 def set(self,x):self.x=x
class Button:
 def config(self,**k):self.k=k
class Thread:
 def __init__(self,target,**kw):self.target=target
 def start(self):self.target()
class Port:
 closed=False
 def reset_input_buffer(self):pass
 def write(self,b):assert b==b'h\n'
 def close(self):self.closed=True
class Channel:
 def __init__(self,chunks):self.chunks=iter(chunks);self.current=next(self.chunks,None);self.closed=False
 def recv_ready(self):return self.current is not None
 def recv(self,n):
  x=self.current;self.current=next(self.chunks,None);return x
 def exit_status_ready(self):return self.current is None and mode!='timeout'
class Client:
 def __init__(self):self.closed=False;clients.append(self)
 def load_system_host_keys(self):pass
 def load_host_keys(self,p):pass
 def set_missing_host_key_policy(self,x):pass
 def connect(self,*a,**kw):
  assert kw['auth_timeout']==12 and not kw['allow_agent']
  if mode=='auth_fail':raise TimeoutError('authentication timed out')
 def exec_command(self,*a,**kw):
  assert kw['timeout']==10
  if mode=='cancel':app.cancel_connect.set()
  parts=[b'\x1b[2K\rEVENT {"eve',b'nt":"ready"}\r\nRX_',b'READY\n'] if mode=='stream' else []
  return None,types.SimpleNamespace(channel=Channel(parts)),None
 def close(self):self.closed=True
clients=[];ports=[]
def serial_open(*a,**kw):
 if mode=='busy':raise PermissionError('port busy')
 p=Port();ports.append(p);return p
clock=[0]
def monotonic():clock[0]+=25;return clock[0]
for mode in ['busy','auth_fail','stream','timeout','cancel']:
 app=monitor.App.__new__(monitor.App)
 app.root=types.SimpleNamespace(after=lambda *a:None);app.q=queue.Queue();app.ser=None;app.ssh=None;app.ready=False;app.connecting=False;app.closing=False;app.pending=None;app.jobs=[];app.auto=False
 app.port=V('COM5');app.host=V('192.168.126.49');app.password=V('test');app.status=V();app.result=V();app.connect_button=Button();app.result_label=Button();app.note=lambda s:None
 with patch.dict(sys.modules,{'serial':types.SimpleNamespace(Serial=serial_open),'paramiko':types.SimpleNamespace(SSHClient=Client,RejectPolicy=lambda:None)}),patch.object(monitor.threading,'Thread',Thread),patch.object(monitor.time,'sleep',lambda n:None),patch.object(monitor.time,'monotonic',monotonic):
  app.connect()
  messages=list(app.q.queue)
  if mode=='stream':assert any(k=='board_line' and 'EVENT' in v and 'ready' in v for k,v in messages),messages
  if mode=='timeout':assert any(k=='lost' and '45秒' in v for k,v in messages),messages
  app.poll()
  assert app.connect_button.k['state']=='normal' and not app.ready and not app.connecting
  assert app.ser is None and app.ssh is None
assert all(x.closed for x in ports+clients)
print('PASS: busy port, auth failure, fragmented ANSI ready, initialization timeout, cancel; all resources released')
