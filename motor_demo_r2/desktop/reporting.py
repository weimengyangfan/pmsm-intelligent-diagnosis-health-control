"""Export measured runs only. No synthetic performance or fallback predictions."""
import html,json,math,statistics
from experiment import result_summary,valid_result

def json_safe(value):
    """Keep invalid numeric evidence exportable without nonstandard JSON numbers."""
    if isinstance(value,float) and not math.isfinite(value):return {'invalid_numeric_value':repr(value)}
    if isinstance(value,dict):return {k:json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    return value

def feedback_requests(bundle):
    out=[]
    for run in bundle['runs']:
        if run['mode']!='continuous':continue
        for r in run['results']:
            if r.get('state')=='result' and valid_result(r.get('packet')) and r.get('confirmed_rule',{}).get('transition')=='alarm':
                out.append(dict(run_id=run['id'],seq=r['seq'],diagnosis=r['predicted'],sim_request_time_s=r['raw_cycle_end_s'],confirmation_cycles=3,executed=False,source='measured NPU classification + PC confirmation rule'))
    return dict(schema='simulation_feedback_request_v1',provenance=bundle.get('provenance',{}),notice='Requests derived from measured diagnosis. No simulation execution is implied.',requests=out)

def report_html(bundle):
    esc=lambda value:html.escape(str(value))
    def table(headers,rows):
        return '<table><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table>'
    def median_text(values,unit,scale=1):
        values=[v for v in values if isinstance(v,(int,float)) and math.isfinite(v) and v>=0]
        return f'{statistics.median(values)*scale:.3f} {unit}' if values else '无记录'
    chunks=[];requests=feedback_requests(bundle)['requests']
    for run in bundle['runs']:
        rs=run['results'];s=result_summary(rs)
        valid=[r for r in rs if r.get('state')=='result' and valid_result(r.get('packet'))]
        pct=lambda n:f'{n}/{s["valid"]}（{n/s["valid"]:.1%}）' if s['valid'] else '无有效结果'
        trips=[r['raw_upload_ms']+r['pc_roundtrip_ms'] for r in valid if r.get('raw_upload_ms') is not None and r.get('pc_roundtrip_ms') is not None]
        npu_time=median_text([r.get('npu_forward_read_ms') for r in valid],'ms')
        full_time=median_text(trips,'s',.001)
        rows=[[r.get('experiment_cycle_index','—'),r.get('phase','—'),r.get('expected','—'),r.get('predicted') or '无有效结果',r.get('baseline_prediction') or '无有效结果',r.get('confirmed_rule',{}).get('status','未启用'),r.get('feature_max_error_A','—'),r.get('state','—')] for r in rs]
        details=table(['窗口','阶段','回放标签','NPU实测','最近中心基线','三周期规则','均值误差/A','结果状态'],rows)
        levels=''
        if run['mode']=='perturbed':
            groups=s['by_perturbation']
            levels='<h3>均值特征扰动对照</h3>'+table(['受控扰动上界/A','有效次数','NPU符合次数','基线符合次数'],[[k,v['count'],v['npu_correct'],v['baseline_correct']] for k,v in sorted(groups.items(),key=lambda p:float(p[0]))])+'<p>对相同17个原始周期重用固定随机偏移，3个幅值层级；不是51次独立电机试验，也不是ADC时域噪声测试。</p>'
        count=sum(r['run_id']==run['id'] for r in requests)
        chunks.append(f'<section><h2>{esc(run["name"])} · {esc(run["status"])}</h2><p>运行ID：{esc(run["id"])}。已记录 {s["total"]}/{run.get("planned_count","—")}；有效 {s["valid"]}，无效 {s["invalid"]}。</p><p>NPU符合标签 {pct(s["npu_correct"])}；最近中心基线 {pct(s["baseline_correct"])}。有效结果上的NPU推理/读取中位数 {npu_time}；原始点上传至返回结果中位耗时 {full_time}。后者包含UART握手、SPI、NPU和网络，不是单个算子的耗时。</p><p>同一批NPU分类上的单次报警事件 {s["instant_alarm_events"]}；三周期确认报警事件 {s["confirmed_alarm_events"]}；确认恢复 {s["confirmed_recovery_events"]}；短暂阶段报警 {s["transient_instant_alarms"]} → {s["transient_confirmed_alarms"]}。非连续模式不启用报警规则。</p>{levels}{details}<p>实测确认产生的仿真停机请求：{count}条。仅导出请求，尚不等于Simulink已执行；执行回执需另行验证。</p></section>')
    payload=esc(json.dumps(bundle['provenance'],ensure_ascii=False,indent=2))
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>电流哨兵 · 实验记录</title><style>body{font:15px/1.7 "Microsoft YaHei",sans-serif;max-width:1200px;margin:35px auto;padding:0 20px;color:#18334c}h1,h2{color:#174e88}section{border-top:2px solid #d4e1ef;margin-top:28px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border:1px solid #d4e1ef;padding:7px}th{background:#eaf2fa}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{background:#fff4df;padding:14px}</style><h1>电机采样偏移监测 · 实板联合验证</h1><p class="note">输入为仿真波形；F4计算、SPI通信和NPU推理为实板过程。本报告只汇总导出的实际会话；控制闭环、实时处理能力和真实电机泛化均未据此验证。报警确认与最近中心基线在PC执行，不与NPU作速度优劣比较。有效分类率的分母为有效结果，无效结果另列，不能把它省略成整体成功率。</p>'+''.join(chunks)+'<h2>来源与参数</h2><pre>'+payload+'</pre></html>'
