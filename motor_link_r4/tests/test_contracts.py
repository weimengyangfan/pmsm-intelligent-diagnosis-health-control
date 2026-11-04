"""Software fixtures only: never report these as MATLAB or NPU execution."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'board'))
sys.path.insert(0, str(ROOT/'desktop'))
from r4_policy import LABELS, Policy, validate_packet
from bridge import Backend, atomic_json, encode_points


def packet(seq, label, b=0., c=0.):
    import binascii
    data = struct.pack('<BBBBHff', 0xA5, 0x5A, 1, 0, seq, b, c)
    data += struct.pack('<H', binascii.crc_hqx(data, 0xffff))
    scores = [-1.]*17
    scores[LABELS.index(label)] = 2.
    return dict(seq=seq, packet_hex=data.hex(), received=[b, c],
                npu=dict(scores=scores, label=label, class_index_1based=LABELS.index(label)+1,
                         top_tied=False, forward_read_ms=.5))


def arm(seq, index=0, b=0., c=0., direction=1):
    return dict(case_id='test', seq=seq, mean_hex=[struct.pack('<f', v).hex() for v in (b,c)],
                source_start_s=.9+.01*index, source_end_s=.91+.01*index, direction=direction)


class Contracts(unittest.TestCase):
    def test_consecutive_and_latch(self):
        p = Policy();p.reset('test')
        for i, label in enumerate(['B_+0.2A', 'Normal', 'B_+0.2A', 'B_+0.2A', 'B_+0.2A', 'Normal']):
            d = p.accept(arm(i,i), packet(i,label))
            self.assertEqual(d['newly_confirmed'], i == 4)
            self.assertEqual(d['request_ramp_to_zero'], i >= 4)
        p.reset('next_case');self.assertFalse(p.latched)

    def test_different_class_gap_direction_reset(self):
        p=Policy();p.reset('test')
        p.accept(arm(1,0),packet(1,'B_+0.2A'))
        self.assertEqual(p.accept(arm(2,1),packet(2,'C_-0.5A'))['streak'],1)
        self.assertEqual(p.accept(arm(3,3),packet(3,'C_-0.5A'))['streak'],1)
        self.assertEqual(p.accept(arm(4,4,direction=-1),packet(4,'C_-0.5A'))['streak'],1)
        p.gap();self.assertEqual(p.accept(arm(5,5),packet(5,'C_-0.5A'))['streak'],1)

    def test_reject_corruption_duplicate_ties_mismatch(self):
        a=arm(1);good=packet(1,'Normal')
        changes=[lambda p:p.update(seq=2),
                 lambda p:p.update(packet_hex=p['packet_hex'][:-2]+'00'),
                 lambda p:p.update(received=[1.,0.]),
                 lambda p:p['npu'].update(top_tied=True),
                 lambda p:p['npu'].update(label='B_+0.2A'),
                 lambda p:p['npu'].update(scores=[float('nan')]*17),
                 lambda p:p['npu'].update(scores=[1.]*17)]
        for change in changes:
            bad=copy.deepcopy(good);change(bad)
            with self.assertRaises((ValueError,TypeError)):
                validate_packet(bad,a)
        p=Policy();p.reset('test');p.accept(a,good)
        with self.assertRaises(ValueError):p.accept(a,good)
        with self.assertRaises(ValueError):p.validate_arm(dict(arm(2,1),case_id='old_case'))

    def test_raw_encoding_and_limits(self):
        begin, lines, end, golden=encode_points(0x1234,[[0,1,-.5],[.01,3,-.5],[.02,5,-.5]])
        self.assertEqual(golden,[3.,-.5]);self.assertTrue(begin.startswith('~B12340003'))
        self.assertEqual(end,'~E1234\n');self.assertEqual(len(lines),3)
        for bad in ([[0,1,1],[0,2,2],[.01,3,3]],
                    [[0,1,1],[.1,2,2],[.2,3,3]],
                    [[0,1,1],[.01,float('inf'),2],[.02,3,3]]):
            with self.assertRaises(ValueError):encode_points(1,bad)

    def test_backend_arm_before_commit(self):
        order=[]
        class MCU:
            def upload(self,seq,points):
                order.append('upload');return [.2,0.],[struct.pack('<f',v).hex() for v in (.2,0.)],0.
            def send(self,text):order.append('commit')
            def wait(self,*args):order.append('finish')
        class Board:
            def command(self,op,**kwargs):
                order.append(op);self.armed=kwargs.get('arm',{});return 'token'
            def wait(self,token,event,timeout):
                order.append(event)
                if event=='decision':return dict(decision=dict(case_id='test',seq=self.armed['seq']))
                return {}
        backend=Backend(MCU(),Board());backend.case_id='test'
        result=backend.handle(dict(op='cycle',case_id='test',points=[],source_start_s=.9,source_end_s=.91,direction=1))
        self.assertEqual(order,['upload','arm','armed','commit','decision','finish'])
        self.assertEqual(result['mcu_mean'],[.2,0.])
        with self.assertRaises(ValueError):backend.handle(dict(op='cycle',case_id='old'))


if __name__=='__main__':
    unittest.main()
