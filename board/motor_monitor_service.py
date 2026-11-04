#!/usr/bin/env python3
"""Receive STM32 B/C features over existing SPI1 registers, then run ZG330 NPU.
Start this receiver before sending x/y/z to STM32. No FPGA rebuild required.
"""
import argparse
import array
from datetime import timedelta
import json
import math
import mmap
import os
from pathlib import Path
import struct
import sys
import time
from motor_feature_protocol import Decoder

CLASSES = ['Normal','B_+0.1A','B_+0.2A','B_+0.5A','B_+1.0A',
           'B_-0.1A','B_-0.2A','B_-0.5A','B_-1.0A',
           'C_+0.1A','C_+0.2A','C_+0.5A','C_+1.0A',
           'C_-0.1A','C_-0.2A','C_-0.5A','C_-1.0A']

class NPU:
    def __init__(self, base):
        sys.path.insert(0, '/root/run/lib')
        import xir, xrt, zg330backend
        self.xrt = xrt
        prefix = base / 'motor_bias_mlp17_logits_ZG'
        metadata = json.loads(prefix.with_suffix('.json').read_text())
        if metadata['ai_target'] != '@zhuget(330)':
            raise RuntimeError('Expected generated ZG330 model')
        boundaries = [o['op_id'] for o in metadata['ops'] if o['_type_key'] in
                      ('icraft::xir::Input','icraft::xir::Output')]
        compute = [o for o in metadata['ops'] if o['op_id'] not in boundaries]
        if not compute or not all(o['_type_key']=='icraft::xir::HardOp' and
                                  o['compile_target']=='@zhuget(330)' for o in compute):
            raise RuntimeError('Expected hardware-only generated model')
        inp = [o for o in metadata['ops'] if o['_type_key']=='icraft::xir::Input'][0]['outputs'][0]['dtype']
        out = [o for o in metadata['ops'] if o['_type_key']=='icraft::xir::Output'][0]['inputs'][0]['dtype']
        if inp['shape'] != [1,1,1,2] or out['shape'] != [1,17] or inp['element_dtype']!='@fp(32)' or out['element_dtype']!='@fp(32)':
            raise RuntimeError('Unexpected model IO shape/type')
        self.network = xir.Network.CreateFromJsonFile(str(prefix.with_suffix('.json')))
        self.network.loadParamsFromFile(str(prefix.with_suffix('.raw')))
        self.view = self.network.viewExcept(boundaries)
        self.device = xrt.Device.Open('axi://zg330aiu?npu=0x40000000&dma=0x80000000')
        self.device.setWaitTime(10000)
        self.session = xrt.Session.Create([zg330backend.ZG330Backend], self.view, [self.device])
        self.session.apply()
        self.dtype = xir.TensorType(self.view.inputs()[0].dtype)

    def run(self, values):
        buf = array.array('f', values)
        tensor = self.xrt.Tensor(buf, self.dtype)
        start = time.perf_counter()
        outputs = self.session.forward([tensor])
        if len(outputs)!=1 or not outputs[0].waitForReady(timedelta(seconds=12),timedelta(milliseconds=1)):
            raise RuntimeError('NPU output timeout')
        data = bytearray(68)
        outputs[0].read(data,0,68)
        scores = list(struct.unpack('<17f',data))
        if not all(math.isfinite(v) for v in scores):
            raise RuntimeError('Non-finite NPU output')
        tied = scores.count(max(scores))!=1
        index = max(range(17),key=lambda i:scores[i])
        return {'class_index_1based':index+1,'label':CLASSES[index], 'top_tied':tied,
                'scores':scores,'forward_read_ms':(time.perf_counter()-start)*1000}

def read_snapshot(read):
    for _ in range(20):
        before = read(0x90)
        status = read(0x84)
        errors = read(0x94)
        after = read(0x90)
        if before == after:
            return after,status,errors
    raise RuntimeError('Cannot read stable write-count/status pair')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir',default=str(Path(__file__).resolve().parent))
    parser.add_argument('--receive-only',action='store_true')
    parser.add_argument('--once',action='store_true')
    args = parser.parse_args()
    import fcntl
    lock = open('/tmp/motor_monitor_v1.lock','w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    base = Path(args.dir)
    npu = None if args.receive_only else NPU(base)
    fd = os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
    decoder = Decoder()
    log = base / 'spi_feature_results.jsonl'
    try:
        with mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=0x400C0000) as mem:
            def read(offset): return struct.unpack_from('<I',mem,offset)[0]
            if read(0x88)!=0x53504931:
                raise RuntimeError('Expected already-verified SPI1 bitstream')
            previous,_,old_errors=read_snapshot(read)
            print('EVENT '+json.dumps({'event':'ready'}),flush=True)
            print('RX_READY: send x/y/z in STM32 UART window. Ctrl+C exits.',flush=True)
            while True:
                count,status,errors=read_snapshot(read)
                delta=(count-previous)&0xFFFFFFFF
                if errors!=old_errors:
                    decoder.clear(); previous=count; old_errors=errors
                    print('EVENT '+json.dumps({'event':'transport_error','reason':'SPI error counter changed'}),flush=True)
                    print('SPI_ERRORS_CHANGED: packet discarded; resend after checking wiring',flush=True)
                    continue
                if delta:
                    previous=count
                    if delta!=1:
                        decoder.clear()
                        print('EVENT '+json.dumps({'event':'transport_error','reason':'missed writes'}),flush=True)
                        print('RX_GAP: skipped %d writes; packet discarded, resend x/y/z' % (delta-1),flush=True)
                    else:
                        rejects=decoder.rejected
                        packet=decoder.feed(status)
                        if decoder.rejected!=rejects:
                            print('EVENT '+json.dumps({'event':'crc_reject'}),flush=True)
                        if packet:
                            if npu is not None: packet['npu']=npu.run(packet['standardized'])
                            packet['host_time_unix']=time.time()
                            print('EVENT '+json.dumps({'event':'result','packet':packet}),flush=True)
                            with log.open('a',encoding='utf8') as f: f.write(json.dumps(packet,ensure_ascii=False)+'\n')
                            print('FEATURE_RX seq=%d format=%s B=%g C=%g CRC_OK' %
                                  (packet['seq'],packet['format'],*packet['received']),flush=True)
                            if npu is not None:
                                r=packet['npu']; print('NPU_CLASS=%d %s TOP_TIED=%s MS=%.3f' %
                                                      (r['class_index_1based'],r['label'],r['top_tied'],r['forward_read_ms']),flush=True)
                            if args.once: return
                time.sleep(0.002)
    finally:
        os.close(fd)
        lock.close()

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: pass
