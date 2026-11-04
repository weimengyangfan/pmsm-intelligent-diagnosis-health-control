"""Non-real-time original Simulink waveform replay, actual F4 mean computation."""
import json,math,queue,re,threading,time,tkinter as tk
from pathlib import Path
from tkinter import ttk,messagebox
from dashboard import Dashboard,FONT,BLUE,MUTED,INK,friendly
from raw_protocol import lines_for_cycle,unbits
BASE=Path(__file__).parent
RAW=json.loads((BASE/'raw_cycles.json').read_text(encoding='utf-8'))

class RawDashboard(Dashboard):
    def __init__(self,root):
        self.raw_busy=False;self.raw_capable=False;self.raw_text='';self.raw_acks=queue.Queue();self.raw_events=queue.Queue();self.raw_cancel=threading.Event();self.raw_cycle=None
        super().__init__(root)
        root.title('电流哨兵 | 原始仿真波形 → F4特征 → NPU · R1')
        self.raw_tab=ttk.Frame(self.tabs);self.tabs.insert(0,self.raw_tab,text='原始波形回放');self.tabs.select(self.raw_tab)
        self.raw_status=tk.StringVar(value='非实时分批回放：PC划分完整电角周期；F4按实际时间积分求均值。先连接设备。')
        self.raw_result=tk.StringVar(value='尚未计算：只有通过F4/黄金模型比对，才允许把F4计算结果发往NPU。')
        toolbar=ttk.Frame(self.raw_tab);toolbar.pack(fill='x',pady=10)
        self.raw_choice=tk.StringVar(value=friendly('Normal'))
        self.raw_picker=ttk.Combobox(toolbar,textvariable=self.raw_choice,values=[friendly(x['label']) for x in RAW['cycles']],state='readonly',width=25)
        self.raw_picker.pack(side='left');self.raw_picker.bind('<<ComboboxSelected>>',lambda e:self.show_cycle())
        ttk.Button(toolbar,text='回放原始周期并诊断',command=self.raw_start,style='Primary.TButton').pack(side='left',padx=8)
        ttk.Button(toolbar,text='停止后续处理',command=self.stop).pack(side='left')
        ttk.Button(toolbar,text='查看NPU输出',command=self.show_npu).pack(side='left',padx=8)
        ttk.Button(toolbar,text='导出完整记录',command=self.export).pack(side='left')
        ttk.Label(self.raw_tab,textvariable=self.raw_status,foreground=BLUE,wraplength=1100).pack(anchor='w',pady=(0,6))
        ttk.Label(self.raw_tab,textvariable=self.raw_result,foreground=INK,wraplength=1100,font=(FONT,11)).pack(anchor='w',pady=(0,5))
        ttk.Label(self.raw_tab,text='原始波形证据：来源MAT中保留的采样点；仅周期端点插值。偏移按设定离线加在诊断通道，不改变原电机控制。',foreground=MUTED,wraplength=1100).pack(anchor='w')
        self.wave=tk.Canvas(self.raw_tab,bg='white',height=260,highlightthickness=1,highlightbackground='#dae4ee');self.wave.pack(fill='both',expand=True,pady=6)
        self.wave.bind('<Configure>',lambda e:self.draw_wave())
        self.raw_info=tk.StringVar();ttk.Label(self.raw_tab,textvariable=self.raw_info,foreground=MUTED,wraplength=1100).pack(anchor='w',pady=5)
        ttk.Label(self.raw_tab,text='阶段：①原始电流/电角度回放与F4均值计算 ②SPI与NPU真实诊断。本版尚未将诊断结果反馈到Simulink。',foreground=MUTED,wraplength=1100).pack(anchor='w',pady=(0,6))
        self.show_cycle()

    def show_cycle(self):
        selected=next(x for x in RAW['cycles'] if friendly(x['label'])==self.raw_choice.get())
        if self.raw_busy:return
        self.raw_cycle=selected
        self.show_cycle_info(selected)
        self.draw_wave()

    def show_cycle_info(self,cycle):
        self.raw_info.set(f"源文件 {RAW['source_name']}  |  原仿真 {cycle['source_start_s']:.6f}—{cycle['source_end_s']:.6f} s  |  {len(cycle['points'])}点  |  电频率 {cycle['electrical_hz']:.3f} Hz  |  转速 {cycle['rpm']:.2f} rpm\n原始文件 SHA256：{RAW['source_sha256']}")

    def show_npu(self):
        for tab in self.tabs.tabs():
            if self.tabs.tab(tab,'text')=='NPU计算':self.tabs.select(tab);break

    def draw_wave(self):
        if not hasattr(self,'wave') or not self.raw_cycle:return
        c=self.wave;c.delete('all');w=max(c.winfo_width(),600);h=max(c.winfo_height(),200);p=self.raw_cycle['points'];left=60;right=w-25
        amp=max(1,max(abs(v[j]) for v in p for j in (1,2)))*1.1
        y0=h*.30;scale=h*.20/amp
        c.create_line(left,y0,right,y0,fill='#aebdcc');c.create_text(8,18,anchor='w',text='电流 / A：蓝 B相，橙 C相',fill=INK,font=(FONT,10))
        for v in [-amp,0,amp]:c.create_text(30,y0-v*scale,text=f'{v:.1f}',fill=MUTED)
        for channel,color in [(1,BLUE),(2,'#e58b32')]:
            pts=[]
            for row in p:pts.extend([left+(right-left)*row[0]/p[-1][0],y0-row[channel]*scale])
            c.create_line(*pts,fill=color,width=2)
        top=h*.62;bottom=h*.88
        c.create_text(8,top-16,anchor='w',text='电角度相对周期起点 / rad（PC用于划分周期）',fill=INK,font=(FONT,10))
        c.create_line(left,bottom,right,bottom,fill='#aebdcc');pts=[]
        for row in p:pts.extend([left+(right-left)*row[0]/p[-1][0],bottom-(bottom-top)*abs(row[3])/6.283185307])
        c.create_line(*pts,fill='#7a60a8',width=2);c.create_text(30,bottom,text='0',fill=MUTED);c.create_text(30,top,text='2π',fill=MUTED)
        c.create_text(left,h-12,text='0 ms',fill=MUTED);c.create_text(right-30,h-12,text=f'{p[-1][0]*1000:.3f} ms',fill=MUTED)

    def on_serial_text(self,text):
        self.raw_text+=text
        if 'RAW_HOST V1' in self.raw_text:self.raw_capable=True
        while '\n' in self.raw_text:
            line,self.raw_text=self.raw_text.split('\n',1);line=line.strip()
            if line.startswith('RAW_'):self.raw_acks.put(line)
        if len(self.raw_text)>4096:self.raw_text=self.raw_text[-4096:]

    def connect(self):
        if not self.connecting and not self.ssh and not self.ser:
            self.raw_capable=False;self.raw_text=''
        super().connect()

    def start(self,jobs):
        if self.raw_busy:messagebox.showinfo('原始回放进行中','请等待回放完成，或点击停止。');return
        super().start(jobs)

    def raw_start(self,cycle=None):
        if self.raw_busy or self.pending or self.jobs:messagebox.showinfo('任务进行中','请先等待当前任务结束。');return
        if not self.ready or not self.firmware or not self.ser:messagebox.showinfo('尚未就绪','请先连接F4与FPGA服务。');return
        if not self.raw_capable:messagebox.showinfo('需要原始回放固件','当前固件没有RAW_HOST V1标识。请下载本包STM32工程编译的固件；原V1固件不支持原始点积分。');return
        if time.perf_counter()<self.cooldown:return
        if cycle is None:self.show_cycle();cycle=self.raw_cycle
        else:
            self.raw_cycle=cycle
            self.show_cycle_info(cycle)
            self.draw_wave()
        self.seq=(self.seq+1)%65536;seq=self.seq;ser=self.ser;self.raw_busy=True;self.raw_cancel.clear()
        while not self.raw_acks.empty():self.raw_acks.get_nowait()
        self.raw_status.set('正在把原始采样点分批回放给F4；每点等待确认，不按仿真采样率实时发送。')
        self.raw_result.set('等待F4计算；本次还没有NPU诊断。');self.result.set('原始波形上传中，等待F4特征');self.draw_motor(None);self.npu_view.clear('F4正在接收原始采样点')
        self.raw_picker.configure(state='disabled')
        started=time.perf_counter()
        def wait(pattern):
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if self.raw_cancel.is_set():raise RuntimeError('用户停止原始回放')
                try:line=self.raw_acks.get(timeout=.1)
                except queue.Empty:continue
                if line.startswith('RAW_ERROR'):raise RuntimeError(line)
                match=re.fullmatch(pattern,line)
                if match:return match
            raise TimeoutError('F4原始回放应答超时')
        def send(line):
            if self.raw_cancel.is_set():raise RuntimeError('用户停止原始回放')
            ser.write(line.encode('ascii'));ser.flush()
        def work():
            try:
                begin,points,end=lines_for_cycle(seq,cycle['points']);send(begin);wait(f'RAW_BEGIN seq={seq:04X}')
                for i,line in enumerate(points):
                    send(line);wait(f'RAW_ACK seq={seq:04X} index={i:04X}')
                    if i%25==0:self.raw_events.put(('progress',f'F4已确认 {i+1}/{len(points)} 个原始点'))
                send(end);m=wait(f'RAW_RESULT seq={seq:04X} b=([0-9A-F]{{8}}) c=([0-9A-F]{{8}}) points={len(points):04X}')
                means=[unbits(m[1]),unbits(m[2])]
                if not all(math.isfinite(x) for x in means):raise RuntimeError('F4均值返回非有限数，禁止提交NPU')
                error=max(abs(a-b) for a,b in zip(means,cycle['golden_mean']))
                if error>2e-6:raise RuntimeError(f'F4/PC均值不一致，最大误差{error} A；禁止提交NPU')
                self.raw_events.put(('calculated',dict(seq=seq,cycle=cycle,means=means,error=error,upload_ms=(time.perf_counter()-started)*1000,wall_start=started)))
            except Exception as exc:
                try:ser.write(b'~X\n')
                except Exception:pass
                self.raw_events.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        super().poll()
        try:
            while True:
                kind,value=self.raw_events.get_nowait()
                if kind=='progress':self.raw_status.set(value)
                elif kind=='error':
                    self.raw_busy=False;self.raw_picker.configure(state='readonly');self.raw_result.set('原始回放无效：'+value);self.raw_status.set('未提交NPU；可检查后重试');self.npu_view.clear('原始点上传/特征验证失败')
                    if hasattr(self,'on_raw_failure'):self.on_raw_failure(value)
                elif kind=='calculated':
                    if self.raw_cancel.is_set() or not self.ready or not self.ser:
                        try:self.ser.write(b'~X\n')
                        except Exception:pass
                        self.raw_busy=False;self.raw_picker.configure(state='readonly');self.raw_status.set('回放已停止，未提交NPU')
                        if hasattr(self,'on_raw_failure'):self.on_raw_failure('回放已停止，未提交NPU')
                        continue
                    cycle=value['cycle'];means=value['means'];seq=value['seq']
                    self.raw_result.set(f"F4实算 B均值={means[0]:+.8f} A，C均值={means[1]:+.8f} A；与PC黄金模型最大误差 {value['error']:.3g} A")
                    self.raw_status.set('F4均值比对通过；发送提交命令，由F4自行封装计算结果并经SPI送往NPU。')
                    self.total=1;self.task_name='原始波形 → F4 → NPU';self.progress.configure(maximum=1,value=0)
                    self.pending=dict(seq=seq,sample={'id':cycle['id'],'label':cycle['label'],'b':means[0],'c':means[1]},negative=False,started=time.perf_counter(),sent_at=time.time(),source='simulation raw waveform replay',extra=dict(raw_source_sha256=RAW['source_sha256'],raw_cycle_id=cycle['id'],raw_point_count=len(cycle['points']),raw_cycle_start_s=cycle['source_start_s'],raw_cycle_end_s=cycle['source_end_s'],pc_golden_mean=cycle['golden_mean'],mcu_mean=means,feature_max_error_A=value['error'],raw_upload_ms=value['upload_ms']))
                    if hasattr(self,'on_raw_prepared'):self.on_raw_prepared(cycle,value)
                    self.sample_info.set(f"完整周期 {len(cycle['points'])}点 → F4均值 [{means[0]:+.6f}, {means[1]:+.6f}] A → NPU")
                    try:self.ser.write(f'~T{seq:04X}\n'.encode('ascii'));self.ser.flush()
                    except Exception as exc:self.finish('serial_error',error=str(exc))
        except queue.Empty:pass

    def finish(self,state,p=None,error=''):
        was_raw=bool(self.pending and self.pending.get('source')=='simulation raw waveform replay')
        super().finish(state,p,error)
        if was_raw:
            self.raw_busy=False;self.raw_picker.configure(state='readonly')
            self.raw_status.set('原始波形→F4特征→NPU完成，记录可导出。' if state=='result' else '本次诊断无效：'+state)

    def stop(self):
        self.raw_cancel.set();super().stop()
    def disconnect(self):
        self.raw_cancel.set();self.raw_capable=False;super().disconnect()
    def close(self):
        self.raw_cancel.set();super().close()

if __name__=='__main__':
    root=tk.Tk();RawDashboard(root);root.mainloop()
