"""Presentation dashboard. Only matched board events can produce a diagnosis."""
import collections,os,statistics,time,tkinter as tk
from tkinter import ttk,messagebox
from monitor import App as TransportApp,DATA,CLASSES,chinese
from npu_view import NPUView
FONT='Microsoft YaHei' if os.name=='nt' else 'WenQuanYi Zen Hei'
BG='#edf2f7';INK='#152b42';MUTED='#63788c';BLUE='#146fe8';GREEN='#118464';AMBER='#bd6716';RED='#c13939';BORDER='#dae4ee'

def friendly(label):
    if label=='Normal':return '正常 · 无预设偏移'
    phase,amount=label.split('_')
    return f'{phase}相采样{ "偏高" if amount[0]=="+" else "偏低"} {amount}'

def summarize(rows):
    normal=[r for r in rows if not r['negative_test']]
    valid=[r for r in normal if r['state']=='result' and not (r.get('packet') or {}).get('npu',{}).get('top_tied')]
    times=[r['npu_forward_read_ms'] for r in valid if r.get('npu_forward_read_ms') is not None]
    trips=[r['pc_roundtrip_ms'] for r in valid]
    return dict(requests=len(normal),valid=len(valid),correct=sum(r['correct'] for r in valid),invalid=len(normal)-len(valid),negative=sum(r['negative_test'] for r in rows),rejected=sum(r['negative_test'] and r['state']=='crc_reject' for r in rows),npu=statistics.median(times) if times else None,trip=statistics.median(trips) if trips else None)

class Dashboard(TransportApp):
    def __init__(self,root):
        self.root=root;self.q=__import__('queue').Queue();self.ser=None;self.ssh=None;self.ready=False;self.connecting=False
        self.firmware=False;self.serial_text='';self.pending=None;self.jobs=[];self.rows=[];self.seq=__import__('random').randrange(1000,60000)
        self.history=[];self.auto=False;self.closing=False;self.cooldown=0.;self.total=0;self.task_name='尚未开始';self.last_label=None;self.latest_values=None;self.events=[];self.collapsed_ready=False
        root.title('电流哨兵 | 电机采样偏移诊断 · V2.1 NPU');root.geometry('1280x880');root.minsize(1120,780);root.configure(bg=BG)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',font=(FONT,10));style.configure('TFrame',background=BG);style.configure('TLabel',background=BG,foreground=INK)
        style.configure('TButton',padding=(12,8),background='white',foreground=INK,bordercolor=BORDER)
        style.map('TButton',background=[('active','#e3edfb')])
        style.configure('Primary.TButton',background=BLUE,foreground='white');style.map('Primary.TButton',background=[('active','#0b58bc'),('disabled','#9baec4')])
        style.configure('TNotebook',background=BG,borderwidth=0);style.configure('TNotebook.Tab',padding=(20,9))
        style.map('TNotebook.Tab',background=[('selected','white')],foreground=[('selected',BLUE)])
        style.configure('Treeview',rowheight=26,font=(FONT,10),background='white',fieldbackground='white',foreground=INK)
        style.configure('Treeview.Heading',font=(FONT,10,'bold'),background='#e6edf5',foreground=INK)
        self.status=tk.StringVar(value='打开设备连接，连接 F4 与 FPGA 后开始');self.result=tk.StringVar(value='等待实板诊断')
        self.stats=tk.StringVar(value='本次会话尚无测试记录');self.sample_info=tk.StringVar(value='输入：电角周期内的 B/C 相电流均值，单位 A')
        self.port=tk.StringVar(value='COM5');self.host=tk.StringVar(value='192.168.126.49');self.password=tk.StringVar();self.choice=tk.StringVar(value='Normal')
        self.task=tk.StringVar(value='演示就绪 · 选择单次诊断或完整情景');self.explain=tk.StringVar(value='识别电流采样读数是否偏高或偏低，并定位 B/C 相与预设偏移档位。')
        header=tk.Frame(root,bg=INK);header.pack(fill='x')
        title=tk.Frame(header,bg=INK);title.pack(side='left',padx=22,pady=13)
        tk.Label(title,text='电流哨兵',font=(FONT,24,'bold'),bg=INK,fg='white').pack(anchor='w')
        tk.Label(title,text='电机电流采样偏移诊断  /  STM32 × FPGA NPU',font=(FONT,10),bg=INK,fg='#b2c8dd').pack(anchor='w')
        right=tk.Frame(header,bg=INK);right.pack(side='right',padx=22)
        tk.Label(right,text='仿真特征回放 · 实板通信与推理',font=(FONT,11,'bold'),bg=INK,fg='#92c7ff').pack(anchor='e',pady=(0,5))
        ttk.Button(right,text='设备连接 / 断开',command=self.toggle_connection).pack(anchor='e')
        self.connection=tk.Frame(root,bg='white',highlightthickness=1,highlightbackground=BORDER);self.connection.pack(fill='x',padx=18,pady=(10,0))
        for col,(name,var,width,show) in enumerate([('F4 串口',self.port,8,''),('FPGA 地址',self.host,19,''),('root 密码',self.password,13,'*')]):
            tk.Label(self.connection,text=name,bg='white',fg=INK).grid(row=0,column=col*2,padx=(12,4),pady=10)
            ttk.Entry(self.connection,textvariable=var,width=width,show=show).grid(row=0,column=col*2+1)
        self.connect_button=ttk.Button(self.connection,text='连接并启动板端服务',style='Primary.TButton',command=self.connect);self.connect_button.grid(row=0,column=6,padx=12)
        ttk.Button(self.connection,text='取消 / 断开',command=self.disconnect).grid(row=0,column=7,padx=(0,8))
        self.devices=tk.StringVar(value='● F4 未连接     ● FPGA 服务未就绪     ● NPU 尚未返回结果')
        state=ttk.Frame(root);state.pack(fill='x',padx=20,pady=(8,5))
        ttk.Label(state,textvariable=self.devices,foreground=BLUE).pack(side='left')
        self.connection_badge=ttk.Label(state,text='');self.connection_badge.pack(side='right')
        ttk.Label(root,textvariable=self.status,foreground=MUTED,wraplength=1200).pack(anchor='w',padx=20,pady=(0,5))
        cards=tk.Frame(root,bg=BG);cards.pack(fill='x',padx=18)
        self.metrics=[]
        for i,(caption,unit) in enumerate([('本次有效分类','0'),('标签符合率','—'),('NPU 推理 / 读取中位数','—'),('错误包成功拦截','0 / 0')]):
            cards.columnconfigure(i,weight=1)
            f=tk.Frame(cards,bg='white',highlightthickness=1,highlightbackground=BORDER);f.grid(row=0,column=i,sticky='nsew',padx=(0,8) if i<3 else 0)
            tk.Label(f,text=caption,bg='white',fg=MUTED,font=(FONT,10)).pack(anchor='w',padx=14,pady=(8,0))
            v=tk.StringVar(value=unit);self.metrics.append(v)
            tk.Label(f,textvariable=v,bg='white',fg=INK,font=(FONT,21,'bold')).pack(anchor='w',padx=14,pady=(0,8))
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=18,pady=10)
        live=ttk.Frame(self.tabs);test=ttk.Frame(self.tabs);event=ttk.Frame(self.tabs);debug=ttk.Frame(self.tabs)
        npu=ttk.Frame(self.tabs)
        for frame,name in [(live,'现场诊断'),(npu,'NPU计算'),(test,'17类验收'),(event,'事件记录'),(debug,'技术详情')]:self.tabs.add(frame,text=name)
        self.npu_view=NPUView(npu,FONT,CLASSES,friendly)
        controls=ttk.Frame(live);controls.pack(fill='x',pady=(9,7))
        self.selection=tk.StringVar(value=friendly('Normal'))
        ttk.Combobox(controls,textvariable=self.selection,values=[friendly(x) for x in CLASSES],state='readonly',width=24).pack(side='left')
        for label,command,style_name in [('单次诊断',self.single,'TButton'),('正常 → 偏移 → 恢复',self.story,'Primary.TButton'),('停止后续发送',self.stop,'TButton')]:
            ttk.Button(controls,text=label,command=command,style=style_name).pack(side='left',padx=5)
        ttk.Button(controls,text='查看NPU算子',command=lambda:self.tabs.select(npu)).pack(side='left',padx=5)
        self.progress=ttk.Progressbar(controls,length=140,mode='determinate');self.progress.pack(side='right',padx=8)
        ttk.Label(live,textvariable=self.task,foreground=BLUE).pack(anchor='w',pady=(0,6))
        body=tk.Frame(live,bg='white',highlightthickness=1,highlightbackground=BORDER);body.pack(fill='x')
        self.motor=tk.Canvas(body,width=330,height=205,bg='white',highlightthickness=0);self.motor.pack(side='left',padx=(5,15))
        diag=tk.Frame(body,bg='white');diag.pack(side='left',fill='both',expand=True,padx=12,pady=16)
        tk.Label(diag,text='板上 NPU 返回的诊断',bg='white',fg=MUTED,font=(FONT,10)).pack(anchor='w')
        self.result_label=tk.Label(diag,textvariable=self.result,bg='white',fg=MUTED,font=(FONT,21,'bold'),anchor='w',wraplength=720,justify='left');self.result_label.pack(fill='x',pady=(7,8))
        explanation=tk.Label(diag,textvariable=self.explain,bg='white',fg=MUTED,font=(FONT,10),wraplength=500,justify='left');explanation.pack(anchor='w')
        sample_label=tk.Label(diag,textvariable=self.sample_info,bg='white',fg=INK,font=(FONT,10),wraplength=500,justify='left');sample_label.pack(anchor='w',pady=(12,0))
        diag.bind('<Configure>',lambda e:[widget.configure(wraplength=max(250,e.width-10)) for widget in (self.result_label,explanation,sample_label)])
        tk.Label(live,text='接收到的周期均值趋势',bg=BG,fg=INK,font=(FONT,11,'bold')).pack(anchor='w',pady=(10,2))
        self.canvas=tk.Canvas(live,height=100,bg='white',highlightthickness=1,highlightbackground=BORDER);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        ttk.Label(live,text='蓝色 B相 · 橙色 C相 ｜ 横轴为已接收样本序号，连线仅辅助阅读；不是瞬时电流波形。',foreground=MUTED).pack(anchor='w',pady=(3,5))
        self.last_event=tk.StringVar(value='记录：尚未收到样本。每次诊断均等待匹配序号与特征的板端结果。')
        ttk.Label(live,textvariable=self.last_event,foreground=MUTED).pack(anchor='w')
        testbar=ttk.Frame(test);testbar.pack(fill='x',pady=10)
        ttk.Button(testbar,text='开始 17类 × 3轮实板测试',command=self.suite,style='Primary.TButton').pack(side='left')
        ttk.Button(testbar,text='CRC错误包拦截测试',command=self.negative).pack(side='left',padx=8)
        ttk.Button(testbar,text='导出 JSON / CSV',command=self.export).pack(side='left')
        ttk.Label(test,text='统计当前会话；错误CRC测试单独计数。每类通过次数累积，不等同于独立样本数量。',foreground=MUTED).pack(anchor='w',pady=(0,6))
        self.table=self.make_table(test,('类别','请求','有效','符合标签','异常 / 无效'),(300,100,100,130,150))
        for label in CLASSES:self.table.insert('','end',iid=label,values=(friendly(label),0,0,0,0))
        self.timing=tk.StringVar(value='尚无实测耗时');ttk.Label(test,textvariable=self.timing,foreground=BLUE).pack(anchor='w',pady=8)
        ttk.Label(test,textvariable=self.stats,foreground=MUTED).pack(anchor='w',pady=4)
        ttk.Label(event,text='按实际返回结果记录；“符合标签”只是仿真测试集上的核对结果。',foreground=MUTED).pack(anchor='w',pady=10)
        self.event_table=self.make_table(event,('本机时间','序号','事件','诊断 / 原因'),(120,90,170,620))
        ttk.Button(event,text='导出本次完整记录',command=self.export).pack(anchor='e',pady=8)
        ttk.Label(debug,text='数据路径：电脑仿真特征 → UART → F4 → 电平转换 / SPI → FPGA快照 → Linux → NPU → SSH返回',foreground=INK,wraplength=1150).pack(anchor='w',pady=10)
        ttk.Label(debug,text='模型只接收两项数值特征；仿真标签留在电脑端核对，不传给 NPU。当前不控制电机、不自动补偿。',foreground=MUTED).pack(anchor='w',pady=(0,8))
        self.log=tk.Text(debug,font=('Consolas',10),bg='#14263a',fg='#d7e4f2',wrap='word',relief='flat');self.log.pack(fill='both',expand=True)
        footer=tk.Frame(root,bg=INK);footer.pack(side='bottom',fill='x',before=self.tabs)
        tk.Label(footer,text='验证范围：预设17类采样偏移 · 当前输入为仿真特征 · 真实电机泛化性能尚待验证',bg=INK,fg='#bdcedd',font=(FONT,9)).pack(side='left',padx=18,pady=6)
        self.draw_motor(None);root.protocol('WM_DELETE_WINDOW',self.close);root.after(80,self.poll)

    def make_table(self,parent,columns,widths):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
        for name,width in zip(columns,widths):tree.heading(name,text=name);tree.column(name,width=width,anchor='w' if width>170 else 'center',stretch=True)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y');return tree

    def toggle_connection(self):
        if self.connection.winfo_manager():self.connection.pack_forget()
        else:self.connection.pack(fill='x',padx=18,pady=(10,0),after=self.root.winfo_children()[0])

    def disconnect(self):
        self.npu_view.clear('连接已断开；没有当前NPU诊断')
        self.jobs=[];self.auto=False
        if hasattr(self,'cancel_connect'):self.cancel_connect.set()
        self.ready=False;self.firmware=False
        for resource in (self.ssh,self.ser):
            if resource:
                try:resource.close()
                except Exception:pass
        self.status.set('正在释放连接；完成后可重新连接')
        if not self.connecting and not self.ssh and not self.ser:self.status.set('尚未连接设备')
        self.result.set('连接已断开，当前无有效实时诊断');self.result_label.config(fg=RED);self.draw_motor(None)

    def single(self):
        mapping={friendly(x):x for x in CLASSES};self.choice.set(mapping[self.selection.get()]);super().single()

    def start(self,jobs):
        jobs=list(jobs)
        allowed=not self.pending and not self.jobs and self.ready and self.firmware and self.ser and time.perf_counter()>=self.cooldown
        if allowed:
            self.total=len(jobs);self.task_name='情景演示' if len(jobs)==6 else '17类覆盖测试' if len(jobs)==51 else '错误包拦截测试' if jobs[0][1] else '单次诊断'
            self.progress.configure(maximum=self.total,value=0)
        super().start(jobs)

    def next_job(self):
        super().next_job()
        if self.pending:
            self.npu_view.clear('当前样本正在传输；等待匹配的板端结果')
            done=self.total-len(self.jobs)-1;self.progress.configure(value=done)
            label=self.pending['sample']['label']
            self.task.set(f'{self.task_name}  {done+1} / {self.total}   ·   回放设定：{friendly(label)}')
            self.result.set('正在校验错误包…' if self.pending['negative'] else '正在传输 · 等待板上判断')
            self.explain.set('本次尚未产生诊断，接收到匹配结果后才显示故障位置。')
            self.draw_motor(None)

    def finish(self,state,p=None,error=''):
        if not self.pending:return
        before=self.pending.copy()
        try:super().finish(state,p,error)
        except OSError as exc:
            # A disk/logging failure must not leave a completed request in flight.
            self.pending=None;self.jobs=[];self.auto=False
            self.result.set('记录写入失败 · 请检查磁盘或目录权限');self.result_label.config(fg=RED)
            self.note(str(exc));self.draw_motor(None);return
        row=self.rows[-1]
        if state=='result' and not before['negative']:self.npu_view.update(p)
        else:self.npu_view.clear('CRC错误包已拦截，未提交NPU' if state=='crc_reject' and before['negative'] else '本次没有有效NPU结果：'+state)
        if state=='result' and not before['negative'] and not p['npu'].get('top_tied'):
            label=p['npu']['label'];self.last_label=label;self.latest_values=p['received']
            self.result.set(friendly(label))
            self.explain.set(('本次特征与正常档位一致。' if label=='Normal' else '识别为预设采样偏移档位；当前仅显示诊断，不执行控制补偿。')+('  ✓ 与回放标签一致' if row['correct'] else '  ✗ 与回放标签不一致'))
            self.sample_info.set(f"实收 B均值 {p['received'][0]:+.6f} A    C均值 {p['received'][1]:+.6f} A\nNPU推理/读取 {row['npu_forward_read_ms']:.3f} ms    完整往返 {row['pc_roundtrip_ms']/1000:.3f} s")
            self.draw_motor(label)
        else:
            self.draw_motor(None);self.latest_values=None
            self.explain.set('预期保护行为：校验失败，未提交 NPU。请再发一个正常样本验证恢复。' if state=='crc_reject' and before['negative'] else '本次未产生可用诊断；请查看事件或技术详情。')
        event='错误包已拦截' if state=='crc_reject' and before['negative'] else '诊断完成' if state=='result' else '诊断无效'
        detail=friendly(row['predicted']) if row.get('predicted') else error or state
        self.event_table.insert('','end',values=(time.strftime('%H:%M:%S'),row['seq'],event,detail));self.event_table.yview_moveto(1)
        self.last_event.set(f"最近事件：{event}  ·  序号 {row['seq']}  ·  {detail}")
        self.progress.configure(value=self.total-len(self.jobs))
        if not self.auto:self.task.set(f'{self.task_name} · 已结束；记录可导出')
        self.refresh_stats()

    def refresh_stats(self):
        s=summarize(self.rows)
        for var,value in zip(self.metrics,[str(s['valid']),f"{s['correct']/s['valid']:.1%} ({s['correct']}/{s['valid']})" if s['valid'] else '—',f"{s['npu']:.3f} ms" if s['npu'] is not None else '—',f"{s['rejected']} / {s['negative']}"]):var.set(value)
        for label in CLASSES:
            rs=[r for r in self.rows if not r['negative_test'] and r['expected']==label];z=summarize(rs)
            self.table.item(label,values=(friendly(label),z['requests'],z['valid'],z['correct'],z['invalid']))
        self.timing.set(f"完整往返中位数 {s['trip']/1000:.3f} s · 包含 UART、分段SPI发送、轮询、推理与网络返回。" if s['trip'] is not None else '尚无有效耗时记录')

    def draw_motor(self,label):
        c=self.motor;c.delete('all')
        c.create_text(165,18,text='B / C 采样通道定位示意',fill=MUTED,font=(FONT,10))
        c.create_oval(24,60,124,160,fill='#eff5fc',outline='#b7cbe1',width=2)
        c.create_text(74,100,text='M',fill=INK,font=('Arial',29,'bold'));c.create_text(74,137,text='电机',fill=MUTED,font=(FONT,10))
        phase=label[0] if label and label!='Normal' else None
        for name,y in [('B',78),('C',146)]:
            color=AMBER if phase==name else GREEN if label else '#9aafc4'
            c.create_line(124,y,285,y,fill=color,width=3)
            c.create_rectangle(155,y-18,220,y+18,fill='white',outline=color,width=2)
            c.create_text(188,y,text=f'{name} 采样',fill=color,font=(FONT,11,'bold'))
            c.create_oval(275,y-5,285,y+5,fill=color,outline=color)
        c.create_text(170,195,text='等待本次结果' if not label else 'B/C：正常档位' if label=='Normal' else friendly(label),fill=MUTED if not label else GREEN if label=='Normal' else AMBER,font=(FONT,10,'bold'))

    def draw(self):
        c=self.canvas;c.delete('all');w=max(c.winfo_width(),400);h=max(c.winfo_height(),100);left=53;right=w-22;top=22;bottom=h-30
        middle=(top+bottom)/2;scale=(bottom-top)/2/1.2
        for v in (-1.2,-.6,0,.6,1.2):
            y=middle-v*scale;c.create_line(left,y,right,y,fill='#dee7f0' if v else '#9cb2cb');c.create_text(27,y,text=f'{v:+.1f}',fill=MUTED,font=('Arial',9))
        values=self.history[-60:]
        if not values:c.create_text((left+right)/2,middle-15,text='等待实收特征 · 此处不生成模拟实时波形',fill=MUTED,font=(FONT,12))
        for channel,color in [(0,BLUE),(1,'#e58b32')]:
            pts=[]
            for i,v in enumerate(values):pts.extend([left+i*(right-left)/max(len(values)-1,1),middle-max(-1.2,min(1.2,v[channel]))*scale])
            if len(pts)>=4:c.create_line(*pts,fill=color,width=2)
            for i in range(0,len(pts),2):c.create_oval(pts[i]-2,pts[i+1]-2,pts[i]+2,pts[i+1]+2,fill=color,outline=color)
        if values:
            c.create_text(left,bottom+16,text=str(max(1,len(self.history)-len(values)+1)),fill=MUTED);c.create_text(right,bottom+16,text=str(len(self.history)),fill=MUTED)

    def poll(self):
        super().poll()
        if not self.ready and self.npu_view.packet is not None:self.npu_view.clear('连接未就绪；清除上一条NPU分数')
        if self.ready and self.firmware and not self.collapsed_ready:
            self.connection.pack_forget();self.collapsed_ready=True
        self.devices.set(f"● F4 {'固件已确认' if self.firmware else '未确认'}     ● FPGA服务 {'已就绪' if self.ready else '未就绪'}     ● NPU {'已返回实测结果' if self.ready and self.history else '等待结果'}")
        if not self.ready and not self.pending:self.draw_motor(None)

if __name__=='__main__':
    root=tk.Tk();Dashboard(root);root.mainloop()
