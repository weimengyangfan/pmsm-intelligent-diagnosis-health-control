"""R2: measured raw replay, explicit baselines, temporal confirmation and evidence."""
import copy,hashlib,json,time,uuid,tkinter as tk
from pathlib import Path
from tkinter import ttk,messagebox,filedialog
from raw_dashboard import RawDashboard
from dashboard import FONT,BLUE,GREEN,RED,AMBER,INK,MUTED,friendly
from experiment import Confirmation,nearest_center,valid_result,result_summary
from reporting import report_html,feedback_requests,json_safe
BASE=Path(__file__).parent
SCENARIO_PATH=BASE/'scenarios.json'
SCENARIOS=json.loads(SCENARIO_PATH.read_text(encoding='utf-8'))
SCENARIO_SHA=hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest()
STATE_NAMES={'normal':'正常 · 无持续报警','pending':'偏移待确认','alarm':'持续异常已确认','recovering':'正常输入 · 恢复确认中','invalid':'当前数据无效 · 不确认恢复'}
MODES={'continuous':('完整情景：短暂异常 / 持续偏移 / 恢复','continuous'),'coverage':('17类原始周期核对','coverage'),'perturbed':('51次特征扰动对照','perturbed')}

class DemoDashboard(RawDashboard):
    def __init__(self,root):
        self.run=None;self.runs=[];self.frames=[];self.position=0;self.driving=False;self.scenario_active=False;self.sim_cycle=None;self.last_clock=0
        super().__init__(root)
        root.title('电流哨兵 | 监测过程与对照实验 · R2')
        self.metric_cards.pack_forget()
        for tab in self.tabs.tabs():
            name=self.tabs.tab(tab,'text')
            if name=='现场诊断':self.tabs.tab(tab,text='特征直传（可选）')
            elif name=='17类验收':self.tabs.tab(tab,text='CRC / 特征验收')
        self.demo_tab=ttk.Frame(self.tabs);self.tabs.insert(0,self.demo_tab,text='一键对照实验');self.tabs.select(self.demo_tab)
        bar=ttk.Frame(self.demo_tab);bar.pack(fill='x',pady=(8,5))
        for title,command in [('完整情景演示',lambda:self.begin('continuous')),('17类核对',lambda:self.begin('coverage')),('扰动对照（约8分钟）',lambda:self.begin('perturbed')),('停止演示',self.stop),('导出报告与原始记录',self.export_run)]:
            ttk.Button(bar,text=title,command=command,style='Primary.TButton' if title=='完整情景演示' else 'TButton').pack(side='left',padx=(0,6))
        self.demo_status=tk.StringVar(value='连接设备后开始。每个周期经F4实算与NPU推理，一次完整情景预计约3～4分钟。')
        self.clocks=tk.StringVar(value='非实时分批回放 · 仿真时间与现实时间分开计量')
        self.compare_stats=tk.StringVar(value='对照尚无数据；不会预填准确率或报警结论。')
        ttk.Label(self.demo_tab,textvariable=self.demo_status,foreground=BLUE,wraplength=1150).pack(anchor='w')
        ttk.Label(self.demo_tab,textvariable=self.clocks,foreground=MUTED).pack(anchor='w',pady=3)
        cards=ttk.Frame(self.demo_tab);cards.pack(fill='x',pady=4)
        self.truth_text=tk.StringVar(value='等待回放');self.npu_text=tk.StringVar(value='等待实板结果');self.confirm_text=tk.StringVar(value='等待有效周期')
        for i,(title,var) in enumerate([('回放设定（用于核对）',self.truth_text),('本次 NPU 实测',self.npu_text),('三周期确认规则（PC）',self.confirm_text)]):
            cards.columnconfigure(i,weight=1)
            f=tk.Frame(cards,bg='white',highlightbackground='#dae4ee',highlightthickness=1);f.grid(row=0,column=i,sticky='nsew',padx=(0,6))
            tk.Label(f,text=title,bg='white',fg=MUTED,font=(FONT,9)).pack(anchor='w',padx=10,pady=(5,0))
            tk.Label(f,textvariable=var,bg='white',fg=INK,font=(FONT,12,'bold'),wraplength=340,justify='left').pack(anchor='w',padx=10,pady=(1,6))
        self.inner=ttk.Notebook(self.demo_tab);self.inner.pack(fill='both',expand=True,pady=4)
        overview_host=ttk.Frame(self.inner);data=ttk.Frame(self.inner);guide=ttk.Frame(self.inner)
        for page,title in [(overview_host,'波形与报警过程'),(data,'逐周期对照'),(guide,'应用与验收边界')]:self.inner.add(page,text=title)
        self.overview_scroll=tk.Canvas(overview_host,bg='#edf2f7',highlightthickness=0)
        overview_bar=ttk.Scrollbar(overview_host,orient='vertical',command=self.overview_scroll.yview)
        self.overview_scroll.configure(yscrollcommand=overview_bar.set)
        overview_bar.pack(side='right',fill='y');self.overview_scroll.pack(side='left',fill='both',expand=True)
        overview=ttk.Frame(self.overview_scroll)
        overview_window=self.overview_scroll.create_window((0,0),window=overview,anchor='nw')
        overview.bind('<Configure>',lambda e:self.overview_scroll.configure(scrollregion=self.overview_scroll.bbox('all')))
        self.overview_scroll.bind('<Configure>',lambda e:self.overview_scroll.itemconfigure(overview_window,width=e.width))
        self.feature_text=tk.StringVar(value='F4实算 / PC黄金积分：等待本次计算；最近中心基线：等待实收特征。')
        ttk.Label(overview,textvariable=self.feature_text,foreground=INK,wraplength=1150).pack(anchor='w',pady=(4,1))
        self.timeline=tk.Canvas(overview,height=46,bg='white',highlightthickness=0);self.timeline.pack(fill='x',pady=3);self.timeline.bind('<Configure>',lambda e:self.draw_timeline())
        ttk.Label(overview,text='过程条：灰=未完成/无效，绿=正常或未启用报警，橙=偏移待确认，红=报警保持；逐周期表保留分类差异。',foreground=MUTED,wraplength=1150).pack(anchor='w')
        self.compare_wave=tk.Canvas(overview,height=230,bg='white',highlightthickness=1,highlightbackground='#dae4ee');self.compare_wave.pack(fill='x')
        self.compare_wave.bind('<Configure>',lambda e:self.draw_comparison())
        self.compare_wave.bind('<MouseWheel>',lambda e:self.overview_scroll.yview_scroll(-1 if e.delta>0 else 1,'units'))
        self.compare_wave.bind('<Button-4>',lambda e:self.overview_scroll.yview_scroll(-1,'units'))
        self.compare_wave.bind('<Button-5>',lambda e:self.overview_scroll.yview_scroll(1,'units'))
        ttk.Label(overview,text='上图：灰色健康参考与彩色偏移采样；下图：采样误差（偏移采样−健康参考）。均来自保存的仿真点。',foreground=MUTED,wraplength=1150).pack(anchor='w',pady=4)
        ttk.Label(data,textvariable=self.compare_stats,foreground=BLUE,wraplength=1150).pack(anchor='w',pady=5)
        self.comparison_table=self.make_table(data,('周期','阶段','NPU','最近中心','单次报警','三周期规则'),(65,180,145,145,95,210))
        self.experiment_notes=tk.Text(guide,wrap='word',font=(FONT,11),bg='white',fg=INK,relief='flat');self.experiment_notes.pack(fill='both',expand=True,pady=5)
        self.experiment_notes.insert('1.0','我们在检测什么：电流采样读数的固定偏移，定位B/C相、方向和预设档位。\n\n完整情景：3周期正常 → 1周期短暂B偏移 → 3周期正常 → 4周期B持续偏移 → 3周期正常 → 4周期C持续偏移 → 3周期正常。\n\n规则：连续3个相邻、有效且同相同方向的NPU异常分类确认报警；连续3个正常周期确认恢复。无效数据打断确认，已有报警保持。短暂偏移是实际注入的异常，但本演示约定不升级为持续报警。\n\n对照：①健康/偏移波形；②PC黄金积分/F4积分；③最近中心基线/NPU分类；④同一批NPU输出上的单次报警/三周期确认。当前特征简单，基线可能与NPU同样准确，不预设AI优势。\n\n应用：电机电流采样自检、偏移定位与诊断开发验证。真实电机数据、跨设备泛化、自动补偿均未据此验证。\n\n仿真反馈：仅在实际确认报警后导出停机请求；没有Simulink执行回执时，不能声称完成反馈。当前数据中的偏移只加在诊断通道，不代表控制回路已受损。\n\n17类核对/扰动对照不是连续运行实验，不计三周期报警。扰动为给周期均值增加固定随机偏移，不是ADC时域噪声实验。使用固定随机种子20261101，输出所有成功和失败结果。')
        self.experiment_notes.configure(state='disabled')
        ttk.Label(self.demo_tab,textvariable=self.compare_stats,foreground=MUTED,wraplength=1150).pack(anchor='w',pady=4)

    def begin(self,mode):
        if self.scenario_active or self.raw_busy or self.pending or self.jobs:
            messagebox.showinfo('任务进行中','请等待或停止当前任务。');return
        if not self.ready or not self.ser or not self.firmware:
            messagebox.showinfo('尚未连接','请先连接F4和板端服务。');return
        if not self.raw_capable:
            messagebox.showinfo('固件不匹配','需要已下载的RAW_HOST V1固件。本版不用重新烧录。');return
        name,key=MODES[mode];frames=SCENARIOS[key]
        self.frames=frames;self.position=0;self.scenario_active=True
        self.run=dict(id=uuid.uuid4().hex,name=name,mode=mode,status='running',started_at_unix=time.time(),planned_count=len(frames),scenario_sha256=SCENARIO_SHA,results=[])
        self.runs.append(self.run);self.wall_start=time.perf_counter();self.confirmed=Confirmation(3);self.instant=Confirmation(1)
        self.comparison_table.delete(*self.comparison_table.get_children());self.npu_text.set('等待本次NPU结果');self.confirm_text.set('等待有效周期')
        self.draw_timeline();self._advance(self.run['id'])

    def _advance(self,run_id):
        if not self.scenario_active or self.run['id']!=run_id:return
        if self.raw_busy or self.pending:return
        if self.position>=len(self.frames):self._end('completed');return
        if time.perf_counter()<self.cooldown:
            self.root.after(100,lambda:self._advance(run_id));return
        cycle=self.frames[self.position];self.sim_cycle=cycle
        self.truth_text.set(f"{cycle['phase']}\n{friendly(cycle['label'])}");self.npu_text.set('等待本次实板推理')
        self.feature_text.set('F4实算 / PC黄金积分：等待本次计算；最近中心基线：等待实收特征。')
        self.demo_status.set(f"{self.run['name']} · {self.position+1}/{len(self.frames)} · 上传原始点 → F4积分 → 校核 → SPI → NPU")
        self.driving=True
        try:super().raw_start(cycle)
        finally:self.driving=False
        if not self.raw_busy:self._end('start_failed')
        self.draw_comparison();self.draw_timeline()

    def raw_start(self,cycle=None):
        if self.scenario_active and not self.driving:
            messagebox.showinfo('演示进行中','一键实验运行时请勿另发样本。');return
        super().raw_start(cycle)
    def start(self,jobs):
        if self.scenario_active:
            messagebox.showinfo('演示进行中','一键实验运行时请勿另发样本。');return
        super().start(jobs)

    def on_raw_prepared(self,cycle,value):
        if not self.scenario_active:return
        expected=self.frames[self.position]
        if expected['id']!=cycle['id']:raise RuntimeError('scenario/cycle mismatch')
        self.pending['extra'].update(experiment_id=self.run['id'],experiment_cycle_index=self.position+1,experiment_mode=self.run['mode'],phase=cycle['phase'],perturbation_A=cycle['perturbation_A'],perturbation_delta_A=cycle['perturbation_delta_A'],scenario_sha256=SCENARIO_SHA)
        b,c=value['means'];g=cycle['golden_mean'];baseline=nearest_center(b,c)
        self.feature_text.set(f"F4实算 B={b:+.6f}, C={c:+.6f} A  |  PC黄金 B={g[0]:+.6f}, C={g[1]:+.6f} A\n最大误差 {value['error']:.3g} A（门限2e-6 A） | 最近中心基线（PC）：{baseline or '中心等距，无唯一分类'}")

    def finish(self,state,p=None,error=''):
        pending=self.pending
        in_run=bool(pending and self.scenario_active and pending.get('extra',{}).get('experiment_id')==self.run['id'])
        if in_run:
            c=self.frames[self.position];valid=state=='result' and valid_result(p)
            extra=pending['extra'];extra['baseline_prediction']=nearest_center(*p['received']) if valid else None
            if self.run['mode']=='continuous':
                # Only measured prediction, continuity and validity enter rules.
                label=p['npu']['label'] if valid else None
                extra['instant_rule']=self.instant.step(label,self.position,c['source_start_s'],c['source_end_s'],valid)
                extra['confirmed_rule']=self.confirmed.step(label,self.position,c['source_start_s'],c['source_end_s'],valid)
            else:extra['instant_rule']={};extra['confirmed_rule']={}
            if state=='result' and not valid:
                extra['invalid_output_packet']=copy.deepcopy(p)
                state='invalid_output';p=None;error='NPU输出不完整、非有限、最高分并列或类别与Argmax不一致'
        before=len(self.rows)
        super().finish(state,p,error)
        if not in_run:return
        if len(self.rows)!=before+1:self._end('recording_failed');return
        row=copy.deepcopy(self.rows[-1]);self.run['results'].append(row)
        self.npu_text.set(friendly(row['predicted'])+f"\n推理/读取 {row['npu_forward_read_ms']:.3f} ms" if valid else '本次无有效诊断')
        rule=row.get('confirmed_rule',{})
        if rule:
            self.confirm_text.set(f"{STATE_NAMES[rule['status']]}\n连续异常 {rule['abnormal_count']} · 正常 {rule['normal_count']}（门限3）"+(' · 原报警保持' if rule['status']=='invalid' and rule['alarm_active'] else ''))
        else:self.confirm_text.set('非连续实验 · 不启用报警规则')
        self.comparison_table.insert('','end',values=(self.position+1,c['phase'],row.get('predicted') or '无效',row.get('baseline_prediction') or '无效','报警' if row.get('instant_rule',{}).get('alarm_active') else '—',STATE_NAMES.get(rule.get('status'),'未启用')))
        self.comparison_table.yview_moveto(1);self.position+=1;self.draw_timeline();self.update_comparison_stats()
        if not valid:self._end('invalid_result');return
        if self.run.get('stop_requested'):self._end('stopped');return
        if self.position>=len(self.frames):self._end('completed');return
        # Continue on a valid misclassification: expected labels never decide continuation.
        run_id=self.run['id'];self.root.after(750,lambda:self._advance(run_id))

    def on_raw_failure(self,reason):
        if not self.scenario_active:return
        c=self.frames[self.position];index=self.position
        invalid=dict(state='raw_upload_error',expected=c['label'],predicted=None,phase=c['phase'],experiment_cycle_index=index+1,error=reason,raw_cycle_start_s=c['source_start_s'],raw_cycle_end_s=c['source_end_s'])
        if self.run['mode']=='continuous':
            invalid['confirmed_rule']=self.confirmed.step(None,index,c['source_start_s'],c['source_end_s'],False)
            invalid['instant_rule']=self.instant.step(None,index,c['source_start_s'],c['source_end_s'],False)
        self.run['results'].append(invalid);self.npu_text.set('上传无效 · 未提交NPU');self.confirm_text.set('数据无效；原报警保持' if self.confirmed.alarm else '数据无效；不确认正常')
        self.update_comparison_stats();self._end('stopped' if self.run.get('stop_requested') else 'raw_upload_error')

    def update_comparison_stats(self):
        if not self.run:return
        s=result_summary(self.run['results']);n=s['valid']
        self.compare_stats.set(f"本次有效 {n}/{s['total']} · NPU符合标签 {s['npu_correct']}/{n} · 最近中心基线 {s['baseline_correct']}/{n} · 单次/三周期报警事件 {s['instant_alarm_events']}/{s['confirmed_alarm_events']} · 短暂阶段报警 {s['transient_instant_alarms']}/{s['transient_confirmed_alarms']}")

    def _end(self,status):
        if not self.run:return
        self.scenario_active=False;self.run['status']=status;self.run['finished_at_unix']=time.time();self.update_comparison_stats()
        descriptions={'completed':'已完成，可导出对照报告','stopped':'已停止，保留已测记录','raw_upload_error':'原始上传失败，已停止','invalid_result':'收到无效结果，已停止'}
        self.demo_status.set(descriptions.get(status,'任务已结束：'+status)+f" · {len(self.run['results'])}/{self.run['planned_count']}条")

    def stop(self):
        if self.scenario_active:
            self.run['stop_requested']=True
            if not self.raw_busy and not self.pending:self._end('stopped')
        super().stop()
    def disconnect(self):
        if self.scenario_active:self.run['stop_requested']=True
        super().disconnect()
    def close(self):
        if self.scenario_active:self._end('window_closed')
        super().close()

    def draw_timeline(self):
        if not hasattr(self,'timeline'):return
        c=self.timeline;c.delete('all');w=max(c.winfo_width(),600)
        if not self.run:
            c.create_text(10,22,anchor='w',text='正常 → 短暂偏移 → 正常 → B持续偏移 → 恢复 → C持续偏移 → 恢复',fill=MUTED,font=(FONT,10));return
        width=(w-16)/len(self.frames)
        for i,frame in enumerate(self.frames):
            color='#e3eaf2'
            if i<len(self.run['results']):
                r=self.run['results'][i];rule=r.get('confirmed_rule',{})
                color='#8995a4' if rule.get('status')=='invalid' or r.get('state')!='result' else RED if rule.get('alarm_active') else AMBER if rule.get('status')=='pending' or not r.get('correct') else GREEN
            c.create_rectangle(8+i*width,5,8+(i+1)*width-2,25,fill=color,outline=color)
            if len(self.frames)<=25:c.create_text(8+(i+.5)*width,36,text=str(i+1),fill=MUTED,font=('Arial',8))
        if len(self.frames)>25:c.create_text(10,36,anchor='w',text=f'{self.position}/{len(self.frames)}条已完成；颜色仅按实际返回标记',fill=MUTED,font=(FONT,9))

    def draw_comparison(self):
        if not hasattr(self,'compare_wave'):return
        c=self.compare_wave;c.delete('all');w=max(c.winfo_width(),600);h=max(c.winfo_height(),180)
        if not self.sim_cycle:
            c.create_text(w/2,h/2,text='开始完整情景后，逐周期显示健康参考与偏移采样对照',fill=MUTED,font=(FONT,12));return
        f=self.sim_cycle;p=f['points'];healthy=f['healthy_current'];left=60;right=w-20;duration=p[-1][0]
        amp=max(1.,max(abs(x) for row in p for x in row[1:3]))*1.1
        top0=h*.30;scale=h*.19/amp;bottom0=h*.77;maxerr=max(.3,max(abs(row[j+1]-ref[j]) for row,ref in zip(p,healthy) for j in (0,1)))*1.25
        c.create_text(8,12,anchor='w',text='健康参考（灰虚线） / 偏移采样（B蓝、C橙） · A',fill=INK,font=(FONT,9))
        c.create_line(left,top0,right,top0,fill='#b5c5d6')
        for v in [-amp,0,amp]:c.create_text(30,top0-v*scale,text=f'{v:.1f}',fill=MUTED)
        for j,color in [(0,BLUE),(1,'#e58b32')]:
            points=[];refs=[];errors=[]
            for row,ref in zip(p,healthy):
                x=left+(right-left)*row[0]/duration
                points.extend([x,top0-row[j+1]*scale]);refs.extend([x,top0-ref[j]*scale]);errors.extend([x,bottom0-(row[j+1]-ref[j])*h*.14/maxerr])
            c.create_line(*refs,fill='#9aa9b9',dash=(4,3));c.create_line(*points,fill=color,width=2);c.create_line(*errors,fill=color,width=2)
        c.create_text(8,h*.58,anchor='w',text='采样误差：偏移采样 − 健康参考 · A（单独放大）',fill=INK,font=(FONT,9));c.create_line(left,bottom0,right,bottom0,fill='#b5c5d6')
        for v in [-maxerr,0,maxerr]:c.create_text(30,bottom0-v*h*.14/maxerr,text=f'{v:+.2f}',fill=MUTED)
        c.create_text(left,h-9,text='0 ms',fill=MUTED);c.create_text(right-30,h-9,text=f'{duration*1000:.3f} ms',fill=MUTED)

    def poll(self):
        super().poll()
        if not hasattr(self,'clocks') or not self.run:return
        if time.perf_counter()-self.last_clock<.25:return
        self.last_clock=time.perf_counter()
        if self.scenario_active and self.raw_busy:
            self.demo_status.set(f"{self.run['name']} · {self.position+1}/{len(self.frames)} · {self.raw_status.get()}")
        elapsed=(time.time()-self.run['started_at_unix']) if self.scenario_active else self.run.get('finished_at_unix',time.time())-self.run['started_at_unix']
        end=self.frames[self.position-1]['source_end_s'] if self.position else self.frames[0]['source_start_s'] if self.frames else 0
        self.clocks.set(f"原仿真时间：当前回放至 {end:.6f} s  |  本次现实用时 {elapsed:.1f} s  |  非实时回放，不将仿真周期当作实际响应时间")
        if self.scenario_active and not self.ready and not self.raw_busy and not self.pending:self._end('connection_lost')

    def export_run(self):
        if not self.runs:messagebox.showinfo('暂无记录','请先运行一个实验。');return
        name=filedialog.asksaveasfilename(defaultextension='.json',initialfile='motor_demo_'+time.strftime('%Y%m%d_%H%M%S')+'.json',filetypes=[('JSON实验记录','*.json')])
        if not name:return
        output=Path(name)
        provenance=dict(source_sha256=SCENARIOS['source_sha256'],scenario_sha256=SCENARIO_SHA,random_seed=SCENARIOS['seed'],confirmation_cycles=3,normal_recovery_cycles=3,rule_location='PC desktop',baseline='PC nearest nominal center, identical measured MCU features',real_motor_test=False,real_time=False,simulink_feedback_executed=False,notice=SCENARIOS['notice'])
        bundle=dict(schema='motor_demo_r2',exported_at_unix=time.time(),provenance=provenance,runs=copy.deepcopy(self.runs),session_rows=self.rows)
        bundle=json_safe(bundle)
        try:
            output.write_text(json.dumps(bundle,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            output.with_suffix('.html').write_text(report_html(bundle),encoding='utf-8')
            output.with_name(output.stem+'_feedback_requests.json').write_text(json.dumps(feedback_requests(bundle),ensure_ascii=False,indent=2),encoding='utf-8')
        except (OSError,ValueError) as exc:messagebox.showerror('导出失败',str(exc));return
        self.demo_status.set('已导出JSON、可浏览器查看的HTML报告及待执行的仿真反馈请求：'+str(output))

if __name__=='__main__':
    root=tk.Tk();DemoDashboard(root);root.mainloop()
