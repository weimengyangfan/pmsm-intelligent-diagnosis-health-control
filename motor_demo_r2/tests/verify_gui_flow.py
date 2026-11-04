"""GUI automation with unchanged C integrator plus an explicit NPU TEST FIXTURE.

Run on a development desktop/Xvfb: python tests/verify_gui_flow.py /path/mock_raw
Never use its generated predictions/timings as hardware test evidence.
All generated records stay in a temporary directory.
"""
import json,os,struct,subprocess,sys,tempfile,threading,time,traceback
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import monitor,demo_dashboard
from experiment import LABELS,nearest_center,result_summary

root=tk.Tk();failures=[]
root.report_callback_exception=lambda *args:failures.append(''.join(traceback.format_exception(*args)))
original_after=root.after
root.after=lambda delay,callback=None,*args:original_after(min(delay,3),callback,*args)
app=demo_dashboard.DemoDashboard(root);root.update()
monitor.BASE=Path(tempfile.mkdtemp(prefix='r2_gui_fixture_'))

class Serial:
    in_waiting=0
    def __init__(self):
        self.closed=False;self.force_wrong=False;self.force_tie=False;self.packet_count=0
        self.process=subprocess.Popen(['stdbuf','-o0',sys.argv[1]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        threading.Thread(target=self.read,daemon=True).start()
    def read(self):
        for line in self.process.stdout:
            app.on_serial_text(line)
            if line.startswith('TXPACKET '):
                raw=bytes.fromhex(line.split()[1]);seq=struct.unpack('<H',raw[4:6])[0];mean=list(struct.unpack('<ff',raw[6:14]))
                assert mean==app.pending['extra']['mcu_mean']
                label=nearest_center(*mean)
                if self.force_wrong:label='C_+1.0A' if label!='C_+1.0A' else 'Normal';self.force_wrong=False
                scores=[-4.]*17;scores[LABELS.index(label)]=7.
                if self.force_tie:scores[(LABELS.index(label)+1)%17]=7.
                packet=dict(seq=seq,received=mean,standardized=mean,packet_hex=raw.hex(),test_fixture_only=True,npu=dict(label=label,scores=scores,class_index_1based=LABELS.index(label)+1,top_tied=self.force_tie,forward_read_ms=0.))
                self.force_tie=False;self.packet_count+=1
                app.q.put(('board_line','EVENT '+json.dumps(dict(event='result',packet=packet))))
    def write(self,data):self.process.stdin.write(data.decode('ascii'));self.process.stdin.flush()
    def flush(self):pass
    def close(self):
        if self.closed:return
        self.closed=True;self.process.terminate();self.process.wait()

def until(predicate,seconds=70):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:
        root.update();time.sleep(.002)
        if failures:raise AssertionError(failures)
    root.update();assert predicate(),'GUI flow timeout'

ser=Serial();app.ser=ser;app.ready=app.firmware=True
try:
    until(lambda:app.raw_capable,3)
    app.begin('continuous');until(lambda:not app.scenario_active)
    assert app.run['status']=='completed' and len(app.run['results'])==21
    summary=result_summary(app.run['results'])
    assert (summary['instant_alarm_events'],summary['confirmed_alarm_events'],summary['confirmed_recovery_events'])==(3,2,2)
    assert all(r['feature_max_error_A']<2e-6 for r in app.run['results'])
    app.show_npu();assert app.tabs.tab(app.tabs.select(),'text')=='NPU计算'
    with tempfile.TemporaryDirectory() as temp:
        export=Path(temp)/'fixture_only.json'
        with patch.object(demo_dashboard.filedialog,'asksaveasfilename',return_value=str(export)):app.export_run()
        saved=json.loads(export.read_text(encoding='utf-8'))
        assert len(saved['runs'][0]['results'])==21 and 'test_fixture_only' in export.read_text()
        req=json.loads(export.with_name('fixture_only_feedback_requests.json').read_text())
        assert len(req['requests'])==2 and all(r['executed'] is False for r in req['requests'])
    # A valid wrong prediction must be counted and must NOT stop the comparison.
    ser.force_wrong=True;app.begin('coverage');app.frames=app.frames[:3]
    until(lambda:not app.scenario_active)
    assert len(app.run['results'])==3 and app.run['status']=='completed'
    assert result_summary(app.run['results'])['npu_correct']==2
    # Invalid/tied output stops the run; no fallback to the PC comparator.
    ser.force_tie=True;app.begin('coverage');until(lambda:not app.scenario_active)
    assert app.run['status']=='invalid_result' and len(app.run['results'])==1
    assert result_summary(app.run['results'])['valid']==0
    # Cancel during upload; no delayed next-frame callback may resume it.
    app.begin('continuous');app.stop();until(lambda:not app.scenario_active)
    count=ser.packet_count
    deadline=time.monotonic()+.8
    while time.monotonic()<deadline:root.update();time.sleep(.003)
    assert ser.packet_count==count and app.run['status']=='stopped'
    # A failed local journal write cannot be presented as a recorded success.
    monitor.BASE=monitor.BASE/'missing_directory'
    app.begin('coverage');until(lambda:not app.scenario_active)
    assert app.run['status']=='recording_failed' and not app.run['results']
    assert not failures,failures
    print('PASS: GUI -> actual unchanged C -> SPI bytes; 21-window automation, wrong-class continuation, tied-output stop, cancellation, NPU tab, JSON/HTML/request exports. NPU IS A TEST FIXTURE; NO HARDWARE PERFORMANCE CLAIM.')
finally:
    app.close()
