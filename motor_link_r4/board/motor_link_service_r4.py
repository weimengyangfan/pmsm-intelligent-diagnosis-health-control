"""Wrap the existing accepted service without modifying its NPU/MMIO code.

Run in /root/motor_ai with the SAME environment as motor_monitor_service.py.
Control arrives on SSH stdin; validated decisions leave as R4_EVENT JSON.
The old service's own EVENT output is logged, not used directly by the PC.
"""
import fcntl
import json
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time

from r4_policy import Policy

ANSI = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')


def emit(event, **fields):
    print('R4_EVENT '+json.dumps(dict(event=event, **fields), allow_nan=False), flush=True)


def reader(stream, tag, events):
    for line in stream:
        events.put((tag, line))
    events.put((tag+'_eof', None))


def main():
    base = Path(__file__).resolve().parent
    old = base/'motor_monitor_service.py'
    if not old.is_file():
        raise RuntimeError('Existing motor_monitor_service.py is required in the same directory')
    lock = open('/tmp/motor_link_r4.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another R4 bridge is running; stop its owning terminal first')
    child = subprocess.Popen([sys.executable, '-u', str(old)], cwd=str(base),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    events = queue.Queue()
    threading.Thread(target=reader, args=(child.stdout, 'child', events), daemon=True).start()
    threading.Thread(target=reader, args=(sys.stdin, 'control', events), daemon=True).start()
    policy = Policy(3)
    armed = None
    ready = False
    try:
        while not stopped.is_set():
            try:
                tag, line = events.get(timeout=.1)
            except queue.Empty:
                if child.poll() is not None:
                    raise RuntimeError('Underlying NPU service exited with code '+str(child.returncode))
                continue
            if tag in ('control_eof', 'child_eof'):
                break
            if tag == 'control':
                token = None
                try:
                    if len(line) > 8192:
                        raise ValueError('control message too long')
                    cmd = json.loads(line)
                    token = cmd['token']
                    op = cmd['op']
                    if not ready:
                        raise RuntimeError('NPU service is not ready')
                    if op == 'ping':
                        emit('pong', token=token)
                    elif op == 'reset':
                        if armed is not None:
                            raise ValueError('cannot reset an armed request')
                        policy.reset(cmd['case_id'])
                        emit('reset', token=token, case_id=policy.case_id)
                    elif op == 'gap':
                        if armed is not None:
                            raise ValueError('cannot gap an armed request')
                        policy.gap()
                        emit('gap', token=token, case_id=policy.case_id, latched=policy.latched)
                    elif op == 'arm':
                        if armed is not None:
                            raise ValueError('previous request still armed')
                        arm = cmd['arm']
                        policy.validate_arm(arm)
                        armed = dict(arm=arm, token=token, deadline=time.monotonic()+60)
                        emit('armed', token=token, case_id=policy.case_id, seq=arm['seq'])
                    elif op == 'shutdown':
                        break
                    else:
                        raise ValueError('unknown control operation')
                except Exception as exc:
                    emit('error', token=token, reason=str(exc))
            elif tag == 'child':
                cleaned = ANSI.sub('', line).strip()
                if not cleaned.startswith('EVENT '):
                    print('NPU_LOG '+cleaned, flush=True)
                    continue
                try:
                    event = json.loads(cleaned[6:])
                    if event['event'] == 'ready':
                        ready = True
                        emit('ready', version='R4.0.0', required_cycles=3,
                             real_time=False, hardware_motor_control=False)
                    elif event['event'] == 'result':
                        packet = event['packet']
                        if armed is None or packet.get('seq') != armed['arm']['seq']:
                            emit('ignored', reason='no matching armed sequence')
                            continue
                        current = armed
                        armed = None
                        try:
                            if time.monotonic() > current['deadline']:
                                raise TimeoutError('armed result expired')
                            decision = policy.accept(current['arm'], packet)
                            emit('decision', token=current['token'], packet=packet, decision=decision)
                        except Exception as exc:
                            policy.gap()
                            emit('error', token=current['token'], reason=str(exc))
                    elif event['event'] in ('crc_reject', 'transport_error'):
                        current = armed
                        armed = None
                        policy.gap()
                        emit('error', token=current['token'] if current else None,
                             reason='underlying service: '+str(event))
                except Exception as exc:
                    raise RuntimeError('Malformed underlying service event: '+str(exc))
            if armed is not None and time.monotonic() > armed['deadline']:
                current = armed
                armed = None
                policy.gap()
                emit('error', token=current['token'], reason='NPU result timeout')
    finally:
        # Terminate only the child owned by this wrapper, never other services.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exception:
        emit('fatal', reason=str(exception))
        sys.exit(1)
