"""Windows desktop monitor. All predictions come from the board SSH stream."""
import codecs,csv,json,queue,random,re,struct,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from motor_feature_protocol import crc16
BASE=Path(__file__).resolve().parent
DATA=json.loads((BASE/'samples.json').read_text(encoding='utf-8'))['samples']
CLASSES=list(dict.fromkeys(s['label'] for s in DATA))

ANSI_ESCAPE=re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')

def clean_board_line(line):
    # The SSH PTY carries native runtime colors/cursor erases before EVENT.
    return ANSI_ESCAPE.sub('',line).strip()

def packet(seq,b,c):
    p=struct.pack('<BBBBHff',0xA5,0x5A,1,0,seq,b,c)
    return p+struct.pack('<H',crc16(p))

def matches(pending,p):
    return p['seq']==pending['seq'] and struct.pack('<ff',*p['received'])==struct.pack('<ff',pending['sample']['b'],pending['sample']['c'])

def chinese(label):
    if label=='Normal':return '正常：未识别到预设电流偏移'
    phase,amount=label.split('_')
    return f'{phase} 相电流采样偏移：{amount}'

class App:
    def __init__(self,root):
        self.root=root;self.q=queue.Queue();self.ser=None;self.ssh=None;self.ready=False;self.connecting=False
        self.firmware=False;self.serial_text="";self.pending=None;self.jobs=[];self.rows=[];self.seq=random.randrange(1000,60000)
        self.history=[];self.auto=False;self.closing=False;self.cooldown=0.0
        root.title('电机电流偏移诊断监控台 V1');root.geometry('1180x800');root.minsize(1100,720)
        root.configure(bg='#f3f6fa')
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei',10))
        style.configure('TFrame',background='#f3f6fa')
        style.configure('TLabel',background='#f3f6fa',foreground='#20364b')
        style.configure('TLabelframe',background='#f3f6fa')
        style.configure('TLabelframe.Label',background='#f3f6fa',foreground='#20364b')
        style.configure('TButton',padding=(8,7))
        self.status=tk.StringVar(value='请连接 F4 串口与 FPGA 网络');self.result=tk.StringVar(value='等待输入')
        self.stats=tk.StringVar(value='尚无本次测试记录');self.sample_info=tk.StringVar(value='')
        ttk.Label(root,text='电机电流偏移诊断监控台',font=('Microsoft YaHei',22,'bold')).pack(pady=(12,3))
        ttk.Label(root,text='仿真特征回放  |  STM32F407 实板发送  |  FPGA NPU 实板推理',foreground='#185b80').pack()
        conn=ttk.LabelFrame(root,text='设备连接');conn.pack(fill='x',padx=15,pady=8)
        self.port=tk.StringVar(value='COM5');self.host=tk.StringVar(value='192.168.126.49');self.password=tk.StringVar()
        for col,(title,var,width,show) in enumerate([('F4 串口',self.port,9,''),('FPGA 地址',self.host,20,''),('root 密码',self.password,15,'*')]):
            ttk.Label(conn,text=title).grid(row=0,column=col*2,padx=5,pady=8)
            ttk.Entry(conn,textvariable=var,width=width,show=show).grid(row=0,column=col*2+1)
        self.connect_button=ttk.Button(conn,text='连接并启动板端服务',command=self.connect);self.connect_button.grid(row=0,column=6,padx=10)
        ttk.Label(root,textvariable=self.status,foreground='#185b80').pack()
        box=ttk.Frame(root);box.pack(fill='x',padx=15,pady=8)
        self.choice=tk.StringVar(value='Normal');ttk.Combobox(box,textvariable=self.choice,values=CLASSES,state='readonly',width=20).pack(side='left')
        for title,cmd in [('发送一个样本',self.single),('一键情景演示',self.story),('17类×3轮测试',self.suite),('停止后续发送',self.stop),('CRC错误包测试',self.negative),('导出记录',self.export)]:
            ttk.Button(box,text=title,command=cmd).pack(side='left',padx=3)
        ttk.Label(root,textvariable=self.sample_info,font=('Microsoft YaHei',11)).pack(pady=4)
        self.result_label=tk.Label(root,textvariable=self.result,font=('Microsoft YaHei',23,'bold'),fg='#536374',bg='#eef3f7',pady=16)
        self.result_label.pack(fill='x',padx=15)
        ttk.Label(root,textvariable=self.stats).pack(pady=8)
        self.canvas=tk.Canvas(root,height=200,bg='white',highlightthickness=1,highlightbackground='#d0dae1');self.canvas.pack(fill='x',padx=15)
        ttk.Label(root,text='实际接收的 B/C 周期均值趋势（A）；不是瞬时电流波形。蓝色 B，橙色 C。').pack()
        self.log=tk.Text(root,height=10,font=('Consolas',10));self.log.pack(fill='both',expand=True,padx=15,pady=8)
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(80,self.poll)

    def note(self,s):
        self.log.insert('end',s+'\n');self.log.see('end')
        if int(self.log.index('end-1c').split('.')[0])>600:self.log.delete('1.0','200.0')

    def connect(self):
        if self.connecting or self.ssh or self.ser:return
        port,host,password=self.port.get(),self.host.get(),self.password.get()
        self.connecting=True;self.ready=False;self.firmware=False;self.serial_text=''
        self.cancel_connect=threading.Event()
        self.connect_button.config(state='disabled',text='正在连接…')
        self.status.set(f'连接中；请关闭占用 {port} 的串口助手，并退出旧的板端接收程序')
        def work():
            ser=None;c=None;stage='准备依赖';failure='板端服务已退出，可检查日志后重新连接'
            try:
                import serial,paramiko
                stage='串口'
                self.q.put(('stage','正在打开 F4 串口'))
                ser=serial.Serial(port,115200,timeout=.2,write_timeout=2)
                self.ser=ser
                ser.reset_input_buffer()
                ser.write(b"h\n")
                stage='SSH'
                self.q.put(('stage','正在验证 FPGA SSH 登录'))
                c=paramiko.SSHClient();c.load_system_host_keys()
                known=Path.home()/'.ssh/known_hosts'
                if known.exists():c.load_host_keys(str(known))
                # Refuse unknown or changed keys. Establish trust with Windows ssh first.
                c.set_missing_host_key_policy(paramiko.RejectPolicy())
                c.connect(host,username='root',password=password,timeout=8,banner_timeout=10,auth_timeout=12,look_for_keys=False,allow_agent=False)
                self.ssh=c
                if self.cancel_connect.is_set():return
                stage='板端服务'
                self.q.put(('stage','SSH 已登录；正在加载模型与 NPU（最多45秒）'))
                command='cd /root/motor_ai && LD_LIBRARY_PATH=/root/run/lib:$LD_LIBRARY_PATH PYTHONPATH=/root/run/lib:$PYTHONPATH python3 -u motor_monitor_service.py'
                _,out,err=c.exec_command(command,get_pty=True,timeout=10)
                channel=out.channel
                decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
                buffer='';seen_ready=False;deadline=time.monotonic()+45
                while not self.closing and not self.cancel_connect.is_set():
                    if channel.recv_ready():
                        chunk=channel.recv(32768)
                        if not chunk:break
                        buffer+=decoder.decode(chunk)
                        while '\n' in buffer:
                            line,buffer=buffer.split('\n',1)
                            cleaned=clean_board_line(line)
                            if cleaned.startswith('EVENT '):
                                try:seen_ready=seen_ready or json.loads(cleaned[6:]).get('event')=='ready'
                                except (ValueError,TypeError):pass
                            self.q.put(('board_line',line.rstrip()))
                    elif channel.exit_status_ready() or channel.closed:break
                    elif not seen_ready and time.monotonic()>deadline:
                        raise TimeoutError('45秒内未收到板端就绪消息；请检查旧接收程序是否已退出及板端日志')
                    else:time.sleep(.02)
                if buffer:self.q.put(('board_line',buffer))
                if self.cancel_connect.is_set():failure='连接已断开，可重新连接'
            except Exception as e:
                if stage=='串口':
                    failure=f'无法打开 {port}：请确认端口号，关闭串口助手或其他占用程序，然后重新连接。详情：{e}'
                else:
                    failure=f'{stage}连接失败：{e}'
                    if 'known_hosts' in str(e):failure+='；请先在 CMD 执行 ssh root@'+host+' 核对主机密钥'
            finally:
                # Release partially opened resources BEFORE enabling a new attempt.
                for resource in (c,ser):
                    if resource is not None:
                        try:resource.close()
                        except Exception:pass
                if self.ser is ser:self.ser=None
                if self.ssh is c:self.ssh=None
                if not self.closing:self.q.put(('lost',failure))
        threading.Thread(target=work,daemon=True).start()

    def sample(self,label):return next(s for s in DATA if s['label']==label)
    def start(self,jobs):
        if time.perf_counter()<self.cooldown:
            messagebox.showinfo("发送收尾中","请稍候半秒，让F4完成当前帧收尾。");return
        if not self.firmware:
            messagebox.showinfo('F4固件未就绪','尚未读到 MOTOR MONITOR V1 标识，请先下载本包F4固件，再重开上位机。');return
        if not self.ready or not self.ser:messagebox.showinfo('尚未就绪','请先连接，等待板端服务就绪。');return
        if self.pending or self.jobs:messagebox.showinfo('正在测试','请等待本次任务结束，或先停止后续发送。');return
        self.jobs=list(jobs);self.auto=True;self.next_job()
    def single(self):self.start([(self.sample(self.choice.get()),False)])
    def story(self):self.start([(self.sample(x),False) for x in ['Normal','B_+0.1A','B_+0.5A','Normal','C_-0.5A','Normal']])
    def suite(self):
        jobs=[]
        for _ in range(3):
            items=[(random.choice([s for s in DATA if s['label']==x]),False) for x in CLASSES];random.shuffle(items);jobs.extend(items)
        self.start(jobs)
    def negative(self):self.start([(self.sample('Normal'),True)])
    def stop(self):
        self.jobs=[];self.auto=False;self.status.set('已停止后续发送；当前完整包仍会处理至结束或超时')
    def next_job(self):
        if self.pending or not self.jobs or not self.auto:return
        s,bad=self.jobs.pop(0);self.seq=(self.seq+1)%65536
        data=packet(self.seq,s['b'],s['c'])
        if bad:data=data[:-1]+bytes([data[-1]^1])
        self.pending={'seq':self.seq,'sample':s,'negative':bad,'started':time.perf_counter(),'sent_at':time.time()}
        self.sample_info.set(f"样本 {s['id']}  |  seq={self.seq}  |  仿真标签：{s['label']}  |  B均值={s['b']:+.5f} A   C均值={s['c']:+.5f} A")
        self.result.set('错误包测试中' if bad else '正在传输，等待板上推理结果…');self.result_label.config(fg='#536374')
        try:self.ser.write((('!' if bad else '@')+data.hex()+'\n').encode('ascii'));self.ser.flush()
        except Exception as e:self.finish('serial_error',error=str(e))

    def finish(self,state,p=None,error=''):
        a=self.pending
        if not a:return
        n=p.get('npu',{}) if p else {}
        good=bool(p and n.get('label')==a['sample']['label'] and not n.get('top_tied'))
        row={'seq':a['seq'],'sample_id':a['sample']['id'],'source':a.get('source','simulation replay'),'expected':a['sample']['label'],'b':a['sample']['b'],'c':a['sample']['c'],'negative_test':a['negative'],'state':state,'correct':good,'predicted':n.get('label'),'npu_forward_read_ms':n.get('forward_read_ms'),'pc_roundtrip_ms':(time.perf_counter()-a['started'])*1000,'sent_at_unix':a['sent_at'],'error':error,'packet':p}
        row.update(a.get("extra",{}))
        self.rows.append(row)
        with (BASE/'session_results.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        if state=='result':
            if a['negative']:self.result.set('异常：错误 CRC 包竟收到推理结果');color='#b42318'
            elif n.get('top_tied'):self.result.set('本次预测无效：最高分并列');color='#b42318'
            else:self.result.set(chinese(n['label'])+'  '+('✓符合预期' if good else '✗与标签不一致'));color='#16734b' if n['label']=='Normal' and good else '#b56806' if good else '#b42318'
            self.history.append(p['received']);self.draw()
            self.note(f"seq={a['seq']} CRC通过 NPU={n.get('label')} 推理/读取={n.get('forward_read_ms',0):.3f}ms 完整往返={row['pc_roundtrip_ms']:.1f}ms")
        elif state=='crc_reject' and a['negative']:self.result.set('校验错误包已拒绝，未提交 NPU');color='#16734b'
        else:self.result.set('本次结果无效：'+state);color='#b42318'
        self.result_label.config(fg=color)
        normal=[x for x in self.rows if not x['negative_test']];valid=[x for x in normal if x['state']=='result' and not (x['packet'] or {}).get('npu',{}).get('top_tied')]
        correct=sum(x['correct'] for x in valid)
        self.stats.set(f"本次正常测试请求 {len(normal)} | 有效分类 {len(valid)} | 标签一致 {correct}/{len(valid)} | 异常/无效 {len(normal)-len(valid)} | 错误包测试 {sum(x['negative_test'] for x in self.rows)}")
        self.pending=None;self.cooldown=time.perf_counter()+0.5
        if self.jobs and self.auto and state=='result' and good:self.status.set('当前样本完成，准备下一条');self.root.after(700,self.next_job)
        else:
            self.jobs=[];self.auto=False;self.status.set('任务结束；可导出实际记录。异常后请检查，再手动重新发送。')

    def draw(self):
        c=self.canvas;c.delete('all');w=max(c.winfo_width(),400);h=200
        c.create_line(45,100,w-15,100,fill='#aebdcc');c.create_text(20,100,text='0 A');c.create_text(25,20,text='+1.2');c.create_text(25,180,text='-1.2')
        values=self.history[-60:]
        for channel,color in [(0,'#1674c2'),(1,'#de7c16')]:
            points=[]
            for i,v in enumerate(values):points.extend([50+i*(w-80)/max(len(values)-1,1),100-max(-1.2,min(1.2,v[channel]))*65])
            if len(points)>=4:c.create_line(*points,fill=color,width=2)
            elif points:c.create_oval(points[0]-3,points[1]-3,points[0]+3,points[1]+3,fill=color)

    def poll(self):
        try:
            while True:
                kind,value=self.q.get_nowait()
                if kind=='stage':
                    self.status.set(value);self.note(value)
                elif kind=='lost':
                    self.ready=False;self.firmware=False;self.serial_text='';self.connecting=False
                    if self.pending:self.finish('connection_lost',error=value)
                    self.jobs=[];self.auto=False
                    self.connect_button.config(state='normal',text='连接并启动板端服务')
                    self.status.set(value);self.note(value)
                    self.result.set('连接已断开，当前无有效实时诊断')
                    self.result_label.config(fg='#b42318')
                else:
                    value=clean_board_line(value)
                    if value.startswith('EVENT '):
                        e=json.loads(value[6:]);event=e['event']
                        if event=='ready':
                            self.ready=True;self.connecting=False
                            self.connect_button.config(text='已连接',state='disabled')
                            self.status.set('板端服务就绪；F4固件已确认' if self.firmware else '板端服务就绪；等待 F4 MOTOR MONITOR V1 标识')
                        elif event=='result':
                            if self.pending and matches(self.pending,e['packet']):self.finish('result',e['packet'])
                            else:self.note('忽略不匹配或无在途请求的结果')
                        elif event in ['crc_reject','transport_error']:
                            if self.pending:self.finish(event,error=e.get('reason',''))
                    else:self.note(value)
        except queue.Empty:pass
        except Exception as e:
            self.ready=False;self.note('事件处理错误：'+str(e))
            if self.pending:self.finish('event_error',error=str(e))
        if self.ser and not self.closing:
            try:
                if self.ser.in_waiting:
                    text=self.ser.read(self.ser.in_waiting).decode('ascii',errors='replace');self.note('MCU '+text.strip())
                    self.serial_text=(self.serial_text+text)[-4000:]
                    if hasattr(self,'on_serial_text'):self.on_serial_text(text)
                    if 'MOTOR MONITOR V1' in self.serial_text:
                        self.firmware=True
                        if self.ready and not self.pending:self.status.set('F4固件与板端服务均已就绪')
            except Exception as e:
                if self.pending:self.finish('serial_error',error=str(e))
                self.ready=False;self.firmware=False
                self.result.set('串口已断开，当前诊断无效');self.result_label.config(fg='#b42318')
                self.note('串口读取失败：'+str(e))
                if hasattr(self,'cancel_connect'):self.cancel_connect.set()
                if self.ssh:self.ssh.close()
        if self.pending and time.perf_counter()-self.pending['started']>20:self.finish('timeout')
        if not self.closing:self.root.after(10 if getattr(self,'raw_busy',False) else 80,self.poll)

    def export(self):
        name=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json'),('CSV','*.csv')])
        if not name:return
        if name.endswith('.csv'):
            keys=[k for k in self.rows[0] if k!='packet'] if self.rows else ['seq','state']
            with open(name,'w',newline='',encoding='utf-8-sig') as f:
                out=csv.DictWriter(f,keys,extrasaction='ignore');out.writeheader();out.writerows(self.rows)
        else:Path(name).write_text(json.dumps(self.rows,ensure_ascii=False,indent=2),encoding='utf-8')
        self.status.set('记录已导出：'+name)
    def close(self):
        self.closing=True
        if hasattr(self,'cancel_connect'):self.cancel_connect.set()
        if self.ssh:self.ssh.close()
        if self.ser:self.ser.close()
        self.root.destroy()

if __name__=='__main__':
    root=tk.Tk();App(root);root.mainloop()
