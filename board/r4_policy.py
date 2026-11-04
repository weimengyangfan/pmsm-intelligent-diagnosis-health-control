"""Board-side supervision. Decisions use validated NPU output, never input labels."""
import binascii
import math
import struct

LABELS = ['Normal'] + [f'{p}_{x:+.1f}A' for p in ('B', 'C')
                       for x in (.1, .2, .5, 1., -.1, -.2, -.5, -1.)]


def validate_packet(packet, arm):
    raw = bytes.fromhex(packet['packet_hex'])
    if len(raw) != 16 or raw[:4] != bytes.fromhex('a55a0100'):
        raise ValueError('packet header/format mismatch')
    if binascii.crc_hqx(raw[:14], 0xffff) != struct.unpack('<H', raw[14:])[0]:
        raise ValueError('packet CRC mismatch')
    seq, b, c = struct.unpack('<Hff', raw[4:14])
    if seq != arm['seq'] or packet['seq'] != seq:
        raise ValueError('packet sequence mismatch')
    words = [raw[6:10].hex(), raw[10:14].hex()]
    if words != arm['mean_hex'] or struct.pack('<ff', *packet['received']) != raw[6:14]:
        raise ValueError('received features differ from armed MCU result')
    if not all(math.isfinite(v) for v in (b, c)):
        raise ValueError('nonfinite feature')
    npu = packet['npu']
    scores = npu['scores']
    if len(scores) != 17 or not all(math.isfinite(v) for v in scores):
        raise ValueError('invalid NPU scores')
    maximum = max(scores)
    if npu.get('top_tied') is not False or sum(v == maximum for v in scores) != 1:
        raise ValueError('NPU top-score tie')
    index = scores.index(maximum)
    if npu['class_index_1based'] != index+1 or npu['label'] != LABELS[index]:
        raise ValueError('NPU label/index/scores disagree')
    if not math.isfinite(npu['forward_read_ms']) or npu['forward_read_ms'] < 0:
        raise ValueError('invalid NPU timing')
    return npu['label']


class Policy:
    def __init__(self, count=3):
        self.required = count
        self.case_id = None
        self.reset('not_started')

    def reset(self, case_id):
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 100:
            raise ValueError('invalid case identity')
        self.case_id = case_id
        self.label = None
        self.streak = 0
        self.latched = False
        self.last_end = None
        self.last_direction = None
        self.seen = set()
        self.alarm = None

    def gap(self):
        self.label = None
        self.streak = 0
        self.last_end = None
        self.last_direction = None

    def validate_arm(self, arm):
        if arm['case_id'] != self.case_id:
            raise ValueError('wrong case identity')
        seq = arm['seq']
        if type(seq) is not int or not 0 <= seq <= 65535 or seq in self.seen:
            raise ValueError('invalid or repeated sequence')
        t0, t1 = arm['source_start_s'], arm['source_end_s']
        if not all(math.isfinite(v) for v in (t0, t1)) or not 0 < t1-t0 <= .100001:
            raise ValueError('invalid electrical-cycle duration')
        if self.last_end is not None and t0 < self.last_end-1e-7:
            raise ValueError('out-of-order cycle')
        if arm['direction'] not in (-1, 1):
            raise ValueError('invalid cycle direction')
        if len(arm['mean_hex']) != 2 or any(len(bytes.fromhex(x)) != 4 for x in arm['mean_hex']):
            raise ValueError('invalid mean bits')

    def accept(self, arm, packet):
        self.validate_arm(arm)
        label = validate_packet(packet, arm)
        contiguous = (self.last_end is not None
                      and abs(arm['source_start_s']-self.last_end) <= 1e-7
                      and arm['direction'] == self.last_direction)
        if not contiguous:
            self.gap()
        self.seen.add(arm['seq'])
        self.last_end = arm['source_end_s']
        self.last_direction = arm['direction']
        if label == 'Normal':
            self.label = None
            self.streak = 0
        else:
            self.streak = self.streak+1 if label == self.label else 1
            self.label = label
        newly_confirmed = not self.latched and self.streak >= self.required
        if newly_confirmed:
            self.latched = True
            self.alarm = dict(seq=arm['seq'], label=label,
                              source_time_s=arm['source_end_s'])
        return dict(case_id=self.case_id, seq=arm['seq'], label=label,
                    streak=self.streak, required=self.required,
                    newly_confirmed=newly_confirmed,
                    request_ramp_to_zero=self.latched,
                    alarm=self.alarm, decision_location='board Linux',
                    source_start_s=arm['source_start_s'],
                    source_end_s=arm['source_end_s'])
