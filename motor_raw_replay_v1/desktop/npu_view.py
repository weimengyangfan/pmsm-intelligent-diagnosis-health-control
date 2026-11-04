"""Static compiled model evidence plus actual scores returned by the NPU service."""
import json,math,tkinter as tk
from pathlib import Path
from tkinter import ttk

class NPUView:
    def __init__(self,parent,font,labels,friendly):
        self.font=font;self.labels=labels;self.friendly=friendly;self.packet=None
        self.manifest=json.loads((Path(__file__).parent/'model_evidence/manifest.json').read_text(encoding='utf-8'))
        m=self.manifest
        ttk.Label(parent,text='模型结构说明（静态） · 隐藏层未读取，不展示虚构的神经元实时活动',foreground='#63788c').pack(anchor='w',pady=(8,4))
        graph=tk.Frame(parent,bg='#edf2f7');graph.pack(fill='x',pady=(0,6))
        for i,(title,body) in enumerate([('2项输入','B/C 电流周期均值'),('隐藏层 1 · 16','1×1 Conv2d + ReLU'),('隐藏层 2 · 16','1×1 Conv2d + ReLU'),('17项输出','1×1 Conv2d · logits')]):
            graph.columnconfigure(i,weight=1)
            cell=tk.Frame(graph,bg='white',highlightthickness=1,highlightbackground='#b6ccea');cell.grid(row=0,column=i,sticky='nsew',padx=(0,6))
            tk.Label(cell,text=title,bg='white',fg='#146fe8',font=(font,12,'bold')).pack(pady=(5,0))
            tk.Label(cell,text=body,bg='white',fg='#152b42',font=(font,9)).pack(pady=(0,5))
        ttk.Label(parent,text='609个逻辑参数 = 560个权重 + 49个偏置；每样本560次逻辑MAC（不含硬件补齐及转换开销）。',foreground='#152b42').pack(anchor='w')
        inner=ttk.Notebook(parent);inner.pack(fill='both',expand=True,pady=6)
        outputs=ttk.Frame(inner);compiled=ttk.Frame(inner)
        inner.add(outputs,text='NPU 实测输出');inner.add(compiled,text='编译算子证据')
        self.status=tk.StringVar(value='尚未收到本次NPU结果，分数区为空。')
        self.inputs=tk.StringVar(value='等待板端返回的原始特征、标准化特征和17个分数。')
        ttk.Label(outputs,textvariable=self.status,foreground='#146fe8',wraplength=1120).pack(anchor='w',pady=(6,2))
        ttk.Label(outputs,textvariable=self.inputs,foreground='#152b42',wraplength=1120).pack(anchor='w')
        score_frame=ttk.Frame(outputs);score_frame.pack(fill='both',expand=True,pady=5)
        self.canvas=tk.Canvas(score_frame,bg='white',height=240,highlightthickness=1,highlightbackground='#dae4ee');self.canvas.pack(side='left',fill='both',expand=True)
        score_scroll=ttk.Scrollbar(score_frame,orient='vertical',command=self.canvas.yview);score_scroll.pack(side='right',fill='y');self.canvas.configure(yscrollcommand=score_scroll.set)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        ttk.Label(outputs,text='板端原始logits，可为负值，不是概率；Linux端以Argmax选取类别。分数区可上下滚动。',foreground='#63788c').pack(anchor='w',pady=(3,4),before=score_frame)
        ops=m['operators'];hard=[x for x in ops if x['kind']=='HardOp']
        ttk.Label(compiled,text=f"本地编译文件：{m['target']}  |  {m['compiler']}  |  {len(hard)}个HardOp，其中3个Conv2dNode",foreground='#146fe8').pack(anchor='w',pady=6)
        ttk.Label(compiled,text='原网络：3个Conv2d + 2个ReLU；编译后ReLU不再单独列出。末层17路按32路存储补齐，再裁回17路。',foreground='#152b42',wraplength=1120).pack(anchor='w',pady=(0,4))
        frame=ttk.Frame(compiled);frame.pack(fill='both',expand=True)
        cols=('算子ID','编译节点','输入形状','输出形状','目标')
        tree=ttk.Treeview(frame,columns=cols,show='headings')
        for col,width in zip(cols,(75,180,225,225,160)):
            tree.heading(col,text=col);tree.column(col,width=width,anchor='w' if width>100 else 'center')
        scrollbar=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side='left',fill='both',expand=True);scrollbar.pack(side='right',fill='y')
        for o in ops:tree.insert('','end',values=(o['id'],o['name'],str(o['input_shapes']),str(o['output_shapes']),o['target']))
        ttk.Label(compiled,text='来源：随包 model_evidence/motor_bias_mlp17_logits_ZG.json；这是编译文件证据，不是逐算子硬件性能计数。',foreground='#63788c',wraplength=1120).pack(anchor='w',pady=(5,2))
        ttk.Label(compiled,text='编译文件 SHA256：'+m['sha256'],foreground='#63788c',font=(font,9)).pack(anchor='w')
        ttk.Label(parent,text='分工：F4发送；FPGA接收/快照；Linux标准化/调度/Argmax；厂家ZG330 NPU执行网络。',foreground='#63788c',wraplength=1150).pack(anchor='w',pady=(2,4),before=inner)

    def clear(self,reason):
        self.packet=None;self.status.set(reason);self.inputs.set('本次没有有效NPU输出；不沿用上一条分数。');self.draw()

    def update(self,packet):
        scores=packet['npu']['scores']
        if len(scores)!=len(self.labels) or not all(math.isfinite(x) for x in scores):
            self.clear('输出维度或数值异常，未显示分数');return
        self.packet=packet;n=packet['npu'];rank=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
        top='；'.join(f"{self.labels[i]} {scores[i]:+.4f}" for i in rank[:3])
        self.status.set(f"实测序号 {packet['seq']}  |  推理/读取 {n['forward_read_ms']:.3f} ms  |  Top-3：{top}"+('  [最高分并列，诊断无效]' if n.get('top_tied') else ''))
        raw=', '.join(f'{x:+.6g}' for x in packet['received']);standard=', '.join(f'{x:+.6g}' for x in packet['standardized'])
        self.inputs.set(f"板端实收 B/C = [{raw}] A；板端标准化 = [{standard}]\nFP32输入 [1,1,1,2] → 内部量化计算 → FP32输出 [1,17]")
        self.canvas.yview_moveto(0)
        self.draw()

    def draw(self):
        c=self.canvas;c.delete('all');w=max(c.winfo_width(),600);h=max(c.winfo_height(),350)
        c.configure(scrollregion=(0,0,w,h))
        if self.packet is None:
            c.create_text(w/2,h/2,text='等待匹配的板端NPU输出',fill='#63788c',font=(self.font,12));return
        scores=self.packet['npu']['scores'];maxv=max(max(abs(x) for x in scores),1e-6)
        left=215;right=w-90;zero=(left+right)/2;scale=(right-left)/2/maxv
        step=(h-12)/len(scores);peak=max(scores)
        c.create_line(zero,4,zero,h-4,fill='#9cb2cb')
        for i,(label,score) in enumerate(zip(self.labels,scores)):
            y=6+(i+.5)*step;best=score==peak
            color='#118464' if best else '#9cb9dd'
            c.create_text(8,y,anchor='w',text=self.friendly(label),fill='#152b42',font=(self.font,9))
            x=zero+score*scale
            c.create_rectangle(min(zero,x),y-step*.28,max(zero,x)+.5,y+step*.28,fill=color,outline=color)
            c.create_text(w-12,y,anchor='e',text=f'{score:+.4f}',fill='#118464' if best else '#63788c',font=('Arial',9))
