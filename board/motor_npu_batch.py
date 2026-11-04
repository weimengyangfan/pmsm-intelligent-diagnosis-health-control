#!/usr/bin/env python3
"""Run the saved 374-sample set through one ZG330 hardware session.

Input is already standardized FP32. Compare both ground truth and the saved
ZG quantized Host scores. Uses only interfaces exercised by motor_npu_smoke.py.
"""
import argparse
import array
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import time
import traceback

CLASSES = [
    'Normal', 'B_+0.1A', 'B_+0.2A', 'B_+0.5A', 'B_+1.0A',
    'B_-0.1A', 'B_-0.2A', 'B_-0.5A', 'B_-1.0A',
    'C_+0.1A', 'C_+0.2A', 'C_+0.5A', 'C_+1.0A',
    'C_-0.1A', 'C_-0.2A', 'C_-0.5A', 'C_-1.0A',
]
URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    base = Path(args.dir).resolve()
    json_path = base / 'motor_bias_mlp17_logits_ZG.json'
    raw_path = base / 'motor_bias_mlp17_logits_ZG.raw'
    test_path = base / 'npu_testset.json'
    for path in (json_path, raw_path, test_path):
        require(path.is_file(), 'Missing file: ' + str(path))

    metadata = json.loads(json_path.read_text(encoding='utf-8'))
    test = json.loads(test_path.read_text(encoding='utf-8-sig'))
    require(metadata['ai_target'] == '@zhuget(330)', 'Expected ZG330 model')
    require(test['format_version'] == 1, 'Unsupported test-set format')
    require(test['input_format'] == 'already_standardized_fp32_BC',
            'Unexpected input format')
    require(test['classes'] == CLASSES, 'Class order mismatch')
    inputs = test['inputs']
    references = test['host_scores']
    labels = test['true_labels']
    count = len(inputs)
    require(count == 374 and len(references) == count and len(labels) == count,
            'Expected exactly 374 paired samples')
    for index, (x, ref, label) in enumerate(zip(inputs, references, labels), 1):
        require(len(x) == 2 and all(math.isfinite(v) for v in x),
                'Invalid input at sample %d' % index)
        require(len(ref) == 17 and all(math.isfinite(v) for v in ref),
                'Invalid Host scores at sample %d' % index)
        require(label in CLASSES, 'Unknown label at sample %d' % index)
    require(all(labels.count(name) == 22 for name in CLASSES),
            'Expected 22 ground-truth samples in each of the 17 classes')
    boundary = [op['op_id'] for op in metadata['ops'] if op['_type_key'] in
                ('icraft::xir::Input', 'icraft::xir::Output')]
    compute = [op for op in metadata['ops'] if op['op_id'] not in boundary]
    require(compute and all(op['_type_key'] == 'icraft::xir::HardOp'
                           and op['compile_target'] == '@zhuget(330)'
                           for op in compute), 'Unexpected compute backend')

    sys.path.insert(0, '/root/run/lib')
    import xir
    import xrt
    import zg330backend

    print('Loading generated ZG model; samples:', count, flush=True)
    network = xir.Network.CreateFromJsonFile(str(json_path))
    network.loadParamsFromFile(str(raw_path))
    view = network.viewExcept(boundary)
    require(len(view.inputs()) == len(view.outputs()) == 1,
            'Expected one input and one output')
    in_desc = [op for op in metadata['ops']
               if op['_type_key'] == 'icraft::xir::Input'][0]['outputs'][0]['dtype']
    out_desc = [op for op in metadata['ops']
                if op['_type_key'] == 'icraft::xir::Output'][0]['inputs'][0]['dtype']
    require(in_desc['shape'] == [1, 1, 1, 2]
            and in_desc['element_dtype'] == '@fp(32)', 'Unexpected input interface')
    require(out_desc['shape'] == [1, 17]
            and out_desc['element_dtype'] == '@fp(32)', 'Unexpected output interface')
    dtype = xir.TensorType(view.inputs()[0].dtype)
    device = xrt.Device.Open(URL)
    device.setWaitTime(10000)
    device_version = dict(device.version())
    session = xrt.Session.Create([zg330backend.ZG330Backend], view, [device])
    session.apply()

    result_path = base / ('npu_batch_' + datetime.now().strftime('%Y%m%d_%H%M%S')
                          + '.json')
    report = {
        'complete': False, 'count_expected': count, 'device_url': URL,
        'device_version': device_version,
        'compiler_version': metadata.get('icraft_version'),
        'model_json_sha256': hashlib.sha256(json_path.read_bytes()).hexdigest(),
        'model_raw_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        'testset_sha256': hashlib.sha256(test_path.read_bytes()).hexdigest(),
        'classes': CLASSES, 'samples': [],
        'timing_scope': 'Python forward, output readiness wait and output read; '
                        'excludes input tensor creation and session initialization',
    }

    def save_report():
        temporary = result_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                             encoding='utf-8')
        temporary.replace(result_path)

    print('Running 374 samples on ZG330 NPU (one session).', flush=True)
    try:
        for index, (x, ref, label) in enumerate(zip(inputs, references, labels), 1):
            buffer = array.array('f', x)
            require(buffer.itemsize == 4, 'Expected 32-bit float buffer')
            tensor = xrt.Tensor(buffer, dtype)
            started = time.perf_counter()
            outputs = session.forward([tensor])
            require(len(outputs) == 1, 'Unexpected output count')
            require(outputs[0].waitForReady(timedelta(seconds=12),
                                            timedelta(milliseconds=1)),
                    'Output timed out at sample %d' % index)
            blob = bytearray(68)
            outputs[0].read(blob, 0, len(blob))
            elapsed = (time.perf_counter() - started) * 1000
            scores = list(struct.unpack('<17f', blob))
            require(all(math.isfinite(v) for v in scores),
                    'Non-finite NPU output at sample %d' % index)
            pred = max(range(17), key=lambda i: scores[i])
            host_pred = max(range(17), key=lambda i: ref[i])
            ordered = sorted(scores, reverse=True)
            item = {
                'index_1based': index, 'input_standardized': list(buffer),
                'true_label': label, 'npu_label': CLASSES[pred],
                'host_label': CLASSES[host_pred], 'correct': CLASSES[pred] == label,
                'host_agreement': pred == host_pred,
                'top_tied': ordered[0] == ordered[1],
                'top_margin': ordered[0] - ordered[1],
                'scores': scores, 'host_scores': ref,
                'max_abs_score_difference': max(abs(a - b) for a, b in zip(scores, ref)),
                'forward_and_read_ms': elapsed,
            }
            report['samples'].append(item)
            if not item['correct'] or not item['host_agreement'] or item['top_tied']:
                print('CHECK sample %d: true=%s npu=%s host=%s tied=%s' %
                      (index, label, item['npu_label'], item['host_label'],
                       item['top_tied']), flush=True)
            if index % 25 == 0 or index == count:
                save_report()
                print('NPU progress: %d/%d' % (index, count), flush=True)
    except BaseException as error:
        report['error'] = repr(error)
        save_report()
        print('Partial result saved:', result_path, flush=True)
        raise

    rows = report['samples']
    correct = sum(r['correct'] for r in rows)
    agreed = sum(r['host_agreement'] for r in rows)
    ties = sum(r['top_tied'] for r in rows)
    recall = {}
    matrix = [[0] * 17 for _ in range(17)]
    for row in rows:
        matrix[CLASSES.index(row['true_label'])][CLASSES.index(row['npu_label'])] += 1
    for name in CLASSES:
        selected = [r for r in rows if r['true_label'] == name]
        hits = sum(r['correct'] for r in selected)
        recall[name] = {'correct': hits, 'count': len(selected),
                        'recall': hits / len(selected) if selected else None}
    times = sorted(r['forward_and_read_ms'] for r in rows)
    report.update({
        'complete': True, 'correct_count': correct, 'accuracy': correct / count,
        'host_agreement_count': agreed, 'top_tie_count': ties,
        'per_class': recall, 'confusion_matrix': matrix,
        'max_abs_score_difference': max(r['max_abs_score_difference'] for r in rows),
        'min_top_margin': min(r['top_margin'] for r in rows),
        'timing_ms': {'first': rows[0]['forward_and_read_ms'],
                      'median': statistics.median(times),
                      'p95': times[math.ceil(.95 * count) - 1], 'max': max(times)},
    })
    save_report()
    print('\nNPU accuracy: %.2f%% (%d/%d)' % (100 * correct / count, correct, count))
    for name in CLASSES:
        r = recall[name]
        print('%-10s recall: %.2f%% (%d/%d)' %
              (name, 100 * r['recall'], r['correct'], r['count']))
    print('Misclassified:', count - correct)
    print('NPU/Host class agreement: %.2f%% (%d/%d)' %
          (100 * agreed / count, agreed, count))
    print('NPU top-score ties:', ties)
    print('Max absolute score difference:', report['max_abs_score_difference'])
    print('Forward/read timing ms:', report['timing_ms'])
    print('Saved:', result_path, flush=True)
    if correct == count and agreed == count and ties == 0:
        print('BATCH_PASS: all 374 NPU classifications correct; no top-score ties.')
        return 0
    print('BATCH_REVIEW: inspect misclassified, differing or tied samples.')
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
