"""Replay every new scenario through the unchanged C parser and mocked SPI.

Usage: python tests/verify_c_scenarios.py /path/to/compiled_mock_raw
This checks C arithmetic/protocol, not an ARM board or an NPU.
"""
import json,re,struct,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from raw_protocol import lines_for_cycle
from motor_feature_protocol import crc16

data=json.loads((Path(__file__).resolve().parents[1]/'desktop/scenarios.json').read_text(encoding='utf-8'))
frames=data['continuous']+data['coverage']+data['perturbed'];commands=[]
for i,frame in enumerate(frames,1):
    begin,points,end=lines_for_cycle(i,frame['points'])
    commands.extend([begin,*points,end,f'~T{i:04X}\n'])
run=subprocess.run([sys.argv[1]],input=''.join(commands),text=True,capture_output=True,check=True)
assert 'RAW_ERROR' not in run.stdout,run.stdout[-2000:]
packets=re.findall(r'^TXPACKET ([0-9A-Fa-f]{32})$',run.stdout,re.M)
assert len(packets)==len(frames),(len(packets),len(frames))
worst=0.
for i,(text,frame) in enumerate(zip(packets,frames),1):
    packet=bytes.fromhex(text)
    assert packet[:4]==bytes([0xa5,0x5a,1,0]) and struct.unpack('<H',packet[4:6])[0]==i
    assert crc16(packet[:-2])==struct.unpack('<H',packet[-2:])[0]
    mean=struct.unpack('<ff',packet[6:14]);error=max(abs(a-b) for a,b in zip(mean,frame['golden_mean']))
    worst=max(worst,error);assert error<2e-6
print(f'PASS: unchanged C parser/integrator/packetizer, {len(frames)} windows, 32-nibble SPI mock, maximum mean error {worst:.12g} A; no NPU emulation')
