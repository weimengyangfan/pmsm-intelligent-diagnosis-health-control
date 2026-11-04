import sys,json,subprocess,re,struct,binascii,math
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'desktop'))
from raw_protocol import lines_for_cycle,unbits
cycles=json.loads((root/'desktop/raw_cycles.json').read_text())['cycles']
all_lines=[]
for seq,cycle in enumerate(cycles,100):
 begin,points,end=lines_for_cycle(seq,cycle['points']);all_lines+=[begin,*points,end,f'~T{seq:04X}\n']
r=subprocess.run(['/tmp/motor_raw_uart'],input=''.join(all_lines),text=True,capture_output=True,check=True).stdout
assert 'RAW_ERROR' not in r
results=re.findall(r'RAW_RESULT seq=([0-9A-F]{4}) b=([0-9A-F]{8}) c=([0-9A-F]{8}) points=([0-9A-F]{4})',r)
packets=re.findall(r'TXPACKET ([0-9a-f]{32})',r)
assert len(results)==len(packets)==17
maximum=0
for cycle,result,p in zip(cycles,results,packets):
 means=[unbits(result[1]),unbits(result[2])];errors=[abs(a-b) for a,b in zip(means,cycle['golden_mean'])];maximum=max(maximum,*errors);assert max(errors)<2e-6
 raw=bytes.fromhex(p);assert struct.unpack('<ff',raw[6:14])==tuple(means)
 assert struct.unpack('<H',raw[4:6])[0]==int(result[0],16)
 assert binascii.crc_hqx(raw[:14],65535)==struct.unpack('<H',raw[14:])[0]
# Invalid / interrupted uploads must not produce or reuse a prepared SPI packet.
begin,points,end=lines_for_cycle(42,cycles[0]['points'])
for fault in ['crc','missing','order','nan','time','stale','abort']:
 data=points.copy();head=begin
 if fault=='crc':head=begin[:-5]+'0000\n'
 if fault=='missing':data.pop(5)
 if fault=='order':data[1],data[2]=data[2],data[1]
 if fault=='nan':data[1]=data[1][:6]+'7FC00000'+data[1][14:]
 if fault=='time':data[1]=data[1][:6]+'00000000'+data[1][14:]
 if fault=='stale':end='~E002B\n'
 if fault=='abort':data=data[:5]+['~X\n']
 out=subprocess.run(['/tmp/motor_raw_uart'],input=head+''.join(data)+end+'~T002A\n',text=True,capture_output=True,check=True).stdout
 assert 'TXPACKET' not in out,fault
print('PASS: 17 original-waveform cycles through real C parser/integrator/SPI; max mean error A=',maximum)
print('PASS: raw CRC, missing/out-of-order points, NaN, time order, stale sequence and abort reject transmission')
