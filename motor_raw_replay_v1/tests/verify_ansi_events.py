"""Reproduce runtime ANSI erases prepended to structured SSH events."""
import sys,queue
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import monitor
from types import SimpleNamespace
class Value:
 def set(self,value):self.value=value
class Button:
 def config(self,**kwargs):self.options=kwargs
app=monitor.App.__new__(monitor.App)
app.q=queue.Queue();app.root=SimpleNamespace(after=lambda *args:None)
app.ready=False;app.connecting=True;app.firmware=True;app.ser=None
app.pending=None;app.closing=False;app.status=Value();app.connect_button=Button()
app.note=lambda text:None
prefix='\x1b[2K\r'*8
app.q.put(('board_line',prefix+'EVENT {"event":"ready"}\r\n'))
app.poll()
assert app.ready and not app.connecting
assert app.connect_button.options['text']=='已连接'
assert '已确认' in app.status.value
assert monitor.clean_board_line('\x1b[33mwarning\x1b[0m')=='warning'
assert monitor.clean_board_line('EVENT {"event":"result"}')=='EVENT {"event":"result"}'
app.pending={'seq':12,'sample':{'b':0.5,'c':0.0},'started':0}
seen=[]
def finish(state,packet):
 seen.append((state,packet));app.pending=None
app.finish=finish
app.q.put(('board_line',prefix+'EVENT {"event":"result","packet":{"seq":12,"received":[0.5,0.0]}}'))
app.poll()
assert len(seen)==1 and seen[0][0]=='result'
print('PASS: ANSI-prefixed ready and matching result are handled; plain events retained')
