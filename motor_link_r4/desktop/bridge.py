"""Windows file-RPC bridge: MATLAB -> real F4 -> real FPGA/NPU -> board policy.

No local classification or fallback predictions. Credentials stay in memory.
Uses the unchanged RAW_HOST V1 and feature-nibble protocols.
"""
import argparse
import binascii
import codecs
import getpass
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import struct
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)


def encode_points(seq, points):
    if not 3 <= len(points) <= 4096:
        raise ValueError('RAW_HOST requires 3..4096 points')
    packed = [struct.pack('<fff', *p[:3]) for p in points]
    values = [struct.unpack('<fff', p) for p in packed]
    if any(not all(math.isfinite(v) for v in p) for p in values):
        raise ValueError('nonfinite raw samples')
    if values[0][0] != 0 or not 0 < values[-1][0] <= .100001:
        raise ValueError('invalid cycle time; firmware requires electrical frequency >=10 Hz')
    if any(values[i][0] <= values[i-1][0] for i in range(1, len(values))):
        raise ValueError('time order lost after FP32 conversion')
    if any(abs(v) > 1000 for p in values for v in p[1:]):
        raise ValueError('current exceeds RAW_HOST range')
    crc = 0xffff
    lines = []
    for i, p in enumerate(packed):
        crc = binascii.crc_hqx(struct.pack('<H', i)+p, crc)
        words = struct.unpack('<III', p)
        lines.append('~D%04X%08X%08X%08X\n' % (i, *words))
    area = [0., 0.]
    for prev, cur in zip(values, values[1:]):
        dt = cur[0]-prev[0]
        for j in range(2):
            area[j] += .5*(prev[j+1]+cur[j+1])*dt
    golden = [struct.unpack('<f', struct.pack('<f', x/values[-1][0]))[0] for x in area]
    return f'~B{seq:04X}{len(points):04X}{crc:04X}\n', lines, f'~E{seq:04X}\n', golden


class Board:
    def __init__(self, host, password, log):
        import paramiko
        self.log = log
        self.events = queue.Queue()
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        known = Path.home()/'.ssh/known_hosts'
        if known.exists():
            self.client.load_host_keys(str(known))
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            self.client.connect(host, username='root', password=password, timeout=8,
                                banner_timeout=10, auth_timeout=12,
                                look_for_keys=False, allow_agent=False)
            cmd = ('cd /root/motor_ai && LD_LIBRARY_PATH=/root/run/lib:$LD_LIBRARY_PATH '
                   'PYTHONPATH=/root/run/lib:$PYTHONPATH python3 -u motor_link_service_r4.py')
            self.stdin, out, _ = self.client.exec_command(cmd, get_pty=False, timeout=10)
            self.channel = out.channel
            threading.Thread(target=self._read, daemon=True).start()
            self.wait(None, 'ready', 60)
        except Exception:
            self.client.close()
            raise

    def _read(self):
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        buffer = ''
        try:
            while True:
                if self.channel.recv_ready():
                    chunk = self.channel.recv(32768)
                    if not chunk:
                        break
                    buffer += decoder.decode(chunk)
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = ANSI.sub('', line).strip()
                        self.log('BOARD '+line)
                        if line.startswith('R4_EVENT '):
                            self.events.put(json.loads(line[9:]))
                elif self.channel.exit_status_ready() or self.channel.closed:
                    break
                else:
                    time.sleep(.01)
        except Exception as exc:
            self.events.put(dict(event='fatal', reason=str(exc)))
        self.events.put(dict(event='fatal', reason='SSH service disconnected'))

    def command(self, op, **fields):
        token = uuid.uuid4().hex
        message = dict(op=op, token=token, **fields)
        self.stdin.write(json.dumps(message, allow_nan=False)+'\n')
        self.stdin.flush()
        return token

    def wait(self, token, event, timeout):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                item = self.events.get(timeout=.1)
            except queue.Empty:
                continue
            if item['event'] == 'fatal':
                raise RuntimeError(item.get('reason', 'board service failed'))
            if item.get('token') == token:
                if item['event'] == 'error':
                    raise RuntimeError(item.get('reason', 'board rejected request'))
                if item['event'] == event:
                    return item
        raise TimeoutError('Board did not return '+event)

    def close(self):
        try:
            self.command('shutdown')
        except Exception:
            pass
        self.client.close()


class F4:
    def __init__(self, port, log):
        import serial
        self.log = log
        self.ser = serial.Serial(port, 115200, timeout=.2, write_timeout=2)
        self.buffer = ''
        try:
            self.ser.reset_input_buffer()
            self.send('h\n')
            deadline = time.monotonic()+6
            text = ''
            while time.monotonic() < deadline:
                line = self.readline()
                text += line+'\n'
                if 'RAW_HOST V1' in text:
                    return
            raise RuntimeError('RAW_HOST V1 not seen; verify the existing raw-replay firmware, do not reflash blindly')
        except Exception:
            self.ser.close()
            raise

    def send(self, line):
        self.ser.write(line.encode('ascii'))
        self.ser.flush()

    def readline(self):
        while '\n' not in self.buffer:
            data = self.ser.read(max(1, self.ser.in_waiting))
            if not data:
                return ''
            self.buffer += data.decode('ascii', errors='replace')
            if len(self.buffer) > 16384:
                raise RuntimeError('MCU line exceeds limit')
        line, self.buffer = self.buffer.split('\n', 1)
        self.log('MCU '+line.strip())
        return line.strip()

    def wait(self, pattern, timeout=5):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            line = self.readline()
            if line.startswith('RAW_ERROR') or line.startswith('FAIL:'):
                raise RuntimeError(line)
            match = re.fullmatch(pattern, line)
            if match:
                return match
        raise TimeoutError('MCU did not return '+pattern)

    def upload(self, seq, points):
        begin, lines, end, golden = encode_points(seq, points)
        self.send(begin)
        self.wait(f'RAW_BEGIN seq={seq:04X}')
        for i, line in enumerate(lines):
            self.send(line)
            self.wait(f'RAW_ACK seq={seq:04X} index={i:04X}')
        self.send(end)
        result = self.wait(f'RAW_RESULT seq={seq:04X} b=([0-9A-F]{{8}}) c=([0-9A-F]{{8}}) points={len(points):04X}')
        bits = [struct.pack('<I', int(result[i], 16)) for i in (1, 2)]
        means = [struct.unpack('<f', p)[0] for p in bits]
        if not all(math.isfinite(v) for v in means):
            raise ValueError('MCU returned nonfinite feature')
        error = max(abs(x-y) for x, y in zip(means, golden))
        if error > 2e-6:
            raise ValueError('MCU/golden feature mismatch; not submitting to NPU')
        return means, [p.hex() for p in bits], error

    def close(self):
        try:
            self.send('~X\n')
        except Exception:
            pass
        self.ser.close()


class Backend:
    def __init__(self, f4, board):
        self.f4, self.board = f4, board
        self.seq = secrets.randbelow(50000)+1000
        self.case_id = None

    def handle(self, req):
        op = req['op']
        if op == 'ping':
            token = self.board.command('ping')
            return self.board.wait(token, 'pong', 10)
        if op == 'reset':
            token = self.board.command('reset', case_id=req['case_id'])
            response = self.board.wait(token, 'reset', 10)
            self.case_id = req['case_id']
            return response
        if req.get('case_id') != self.case_id:
            raise ValueError('RPC case mismatch')
        if op == 'gap':
            token = self.board.command('gap')
            return self.board.wait(token, 'gap', 10)
        if op != 'cycle':
            raise ValueError('unsupported operation')
        self.seq = (self.seq+1) % 65536
        started = time.perf_counter()
        means, hexes, error = self.f4.upload(self.seq, req['points'])
        upload_ms = (time.perf_counter()-started)*1000
        arm = dict(case_id=self.case_id, seq=self.seq, mean_hex=hexes,
                   source_start_s=req['source_start_s'], source_end_s=req['source_end_s'],
                   direction=req['direction'])
        token = self.board.command('arm', arm=arm)
        self.board.wait(token, 'armed', 10)
        self.f4.send(f'~T{self.seq:04X}\n')
        response = self.board.wait(token, 'decision', 60)
        # Do not upload another raw cycle while the MCU is finishing SPI transport.
        self.f4.wait(r'FEATURE_TX_SPI_ACK_OK: 32 nibbles; verify Linux CRC/NPU output', 10)
        if response['decision']['case_id'] != self.case_id or response['decision']['seq'] != self.seq:
            raise ValueError('decision identity mismatch')
        response.update(mcu_mean=means, golden_max_error_A=error,
                        raw_upload_ms=upload_ms,
                        wall_roundtrip_ms=(time.perf_counter()-started)*1000)
        return response


def acquire_lock(root):
    f = open(root/'bridge.lock', 'a+b')
    f.seek(0)
    if os.name == 'nt':
        import msvcrt
        if f.read(1) == b'':
            f.write(b'0'); f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime', default=str(ROOT/'runtime'))
    a = ap.parse_args()
    runtime = Path(a.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(runtime)
    for folder in ('inbox', 'outbox'):
        (runtime/folder).mkdir(exist_ok=True)
    session = uuid.uuid4().hex
    def log(text):
        with (runtime/'bridge.log').open('a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S')+' '+text+'\n')
    f4 = board = None
    atomic_json(runtime/'bridge.json', dict(ready=False, bridge_session=session, pid=os.getpid()))
    try:
        print('R4.0.0: close the old dashboard and serial assistant first.')
        port = input('F4 serial port [COM5]: ').strip() or 'COM5'
        host = input('FPGA address [192.168.126.49]: ').strip() or '192.168.126.49'
        password = getpass.getpass('root password (not saved): ')
        f4 = F4(port, log)
        board = Board(host, password, log)
        password = None
        backend = Backend(f4, board)
        atomic_json(runtime/'bridge.json', dict(ready=True, bridge_session=session,
                    pid=os.getpid(), version='R4.0.0', real_time=False))
        print('R4_BRIDGE_READY: return to MATLAB and run run_motor_link_r4. Ctrl+C stops.')
        while True:
            jobs = sorted((runtime/'inbox').glob('*.json'), key=lambda p: p.stat().st_mtime_ns)
            for path in jobs:
                req = json.loads(path.read_text(encoding='utf-8-sig'))
                request_id = req.get('id', path.stem)
                if request_id != path.stem or not re.fullmatch('[a-f0-9]{32}', request_id):
                    raise ValueError('invalid local RPC identity')
                if req.get('bridge_session') != session:
                    response = dict(ok=False, error='request belongs to a different bridge session')
                else:
                    try:
                        print('RPC', req['op'], req.get('source_end_s', ''), flush=True)
                        result = backend.handle(req)
                        response = dict(ok=True, result=result)
                    except Exception as exc:
                        log('FAILED '+str(exc))
                        response = dict(ok=False, error=str(exc))
                        # An uncertain in-flight transport invalidates this bridge session.
                        atomic_json(runtime/'outbox'/path.name, dict(response, id=request_id, bridge_session=session))
                        path.unlink()
                        raise
                atomic_json(runtime/'outbox'/path.name, dict(response, id=request_id, bridge_session=session))
                path.unlink()
            time.sleep(.025)
    finally:
        if board is not None:
            board.close()
        if f4 is not None:
            f4.close()
        atomic_json(runtime/'bridge.json', dict(ready=False, bridge_session=session, pid=os.getpid()))
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Bridge stopped; no further simulation decision is valid.')
    except Exception as exc:
        print('R4_BRIDGE_FAILED:', exc)
        raise SystemExit(1)
