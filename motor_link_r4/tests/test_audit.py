"""Synthetic evidence test for the independent auditor, not a measured result."""
import copy
from pathlib import Path
import struct
import sys
import unittest
import numpy as np

from test_contracts import ROOT, packet
sys.path.insert(0,str(ROOT/'tools'))
from audit_run import audit
from r4_policy import Policy


class EvidenceAudit(unittest.TestCase):
    def test_causality_and_new_current_evidence(self):
        activation=.940025
        t=np.arange(0,1.50001,.001)
        def signal(values):return dict(time=t.tolist(),data=np.asarray(values).tolist())
        evidence=dict(config=dict(sample_s=.000025,ramp_time_s=.25,stop_time_s=1.5),
                      status=dict(completed=True,passed=True),results={})
        for name in ('no_feedback','with_feedback'):
            enabled=name=='with_feedback';case=name;p=Policy();p.reset(case);records=[]
            for i in range(6):
                start=.90+.01*i;end=start+.01;seq=i+1
                points=np.array([[0,.2,0],[.005,.2,0],[.01,.2,0]],dtype=np.float32).astype(float).tolist()
                pk=packet(seq,'B_+0.2A',b=.2)
                arm=dict(case_id=case,seq=seq,source_start_s=start,source_end_s=end,direction=1,
                         mean_hex=[struct.pack('<f',v).hex() for v in (.2,0.)])
                decision=p.accept(arm,pk)
                records.append(dict(segment_stop_s=.94 if i<3 else .96,
                    cycle=dict(source_start_s=start,source_end_s=end,direction=1,points=points),
                    board=dict(packet=pk,decision=decision,mcu_mean=[float(np.float32(.2)),0.])))
            scale=np.clip(1-(t-activation)/.25,0,1) if enabled else np.ones_like(t)
            evidence['results'][name]=dict(case_id=case,records=records,
                activation_s=activation if enabled else [],first_alarm=p.alarm,
                data=dict(R4_DiagnosticB=signal(np.full_like(t,.2)),R4_DiagnosticC=signal(np.zeros_like(t)),
                          RPM=signal(1500*scale),R4_AppliedCommand=signal(1500*scale)))
        self.assertTrue(audit(evidence)['passed'])
        bad=copy.deepcopy(evidence);bad['results']['with_feedback']['activation_s']-=.01
        with self.assertRaises(AssertionError):audit(bad)
        bad=copy.deepcopy(evidence);bad['results']['with_feedback']['records'][-1]['cycle']['points'][1][1]=10.
        with self.assertRaises(AssertionError):audit(bad)


if __name__=='__main__':unittest.main()
