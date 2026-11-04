#!/usr/bin/env python3
"""One saved, already-standardized sample on the FMQL30TAI ZG330 NPU.

Uses the Python signatures exported from this board in motor_runtime_api.txt.
No NumPy, camera, MCU, register writes, clock changes, or Host fallback.
Host reference: SFT output 33 from the SAME input and ZG quantized model.
"""

import argparse
import array
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time
import traceback

CLASSES = [
    "Normal", "B_+0.1A", "B_+0.2A", "B_+0.5A", "B_+1.0A",
    "B_-0.1A", "B_-0.2A", "B_-0.5A", "B_-1.0A",
    "C_+0.1A", "C_+0.2A", "C_+0.5A", "C_+1.0A",
    "C_-0.1A", "C_-0.2A", "C_-0.5A", "C_-1.0A",
]
DEVICE_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    base = Path(args.dir).resolve()
    prefix = "motor_bias_mlp17_logits_ZG"
    json_path = base / (prefix + ".json")
    raw_path = base / (prefix + ".raw")
    input_path = base / "input.ftmp"
    ref_path = base / "33.ftmp"
    for path in (json_path, raw_path, input_path, ref_path):
        check(path.is_file(), "Missing file: " + str(path))

    print("[1/6] Checking model and saved input", flush=True)
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    check(metadata["ai_target"] == "@zhuget(330)", "Expected ZG330 model")
    boundary = [op["op_id"] for op in metadata["ops"]
                if op["_type_key"] in ("icraft::xir::Input", "icraft::xir::Output")]
    compute = [op for op in metadata["ops"] if op["op_id"] not in boundary]
    check(compute and all(op["_type_key"] == "icraft::xir::HardOp"
                         and op["compile_target"] == "@zhuget(330)"
                         for op in compute), "Unexpected compute backend")
    input_op = [op for op in metadata["ops"]
                if op["_type_key"] == "icraft::xir::Input"]
    output_op = [op for op in metadata["ops"]
                 if op["_type_key"] == "icraft::xir::Output"]
    check(len(input_op) == len(output_op) == 1, "Expected one input and output")
    check(input_op[0]["outputs"][0]["dtype"]["shape"] == [1, 1, 1, 2],
          "Unexpected input shape")
    out_meta = output_op[0]["inputs"][0]
    check(out_meta["dtype"]["shape"] == [1, 17]
          and out_meta["dtype"]["element_dtype"] == "@fp(32)",
          "Expected 17 FP32 output scores")

    input_bytes = input_path.read_bytes()
    check(len(input_bytes) == 8, "input.ftmp must contain two FP32 numbers (8 bytes)")
    inputs = struct.unpack("<2f", input_bytes)
    check(all(math.isfinite(v) for v in inputs), "Non-finite input")
    reference = [float(v) for v in ref_path.read_text().split()]
    check(len(reference) == 17 and all(math.isfinite(v) for v in reference),
          "33.ftmp must contain 17 finite Host scores")
    check(reference.count(max(reference)) == 1, "Tied Host reference scores")
    print("Model compiler:", metadata.get("icraft_version"), flush=True)
    print("Input (already standardized B,C):", inputs, flush=True)

    print("[2/6] Loading board runtime and generated ZG model", flush=True)
    sys.path.insert(0, "/root/run/lib")
    import xir
    import xrt
    import zg330backend

    network = xir.Network.CreateFromJsonFile(str(json_path))
    network.loadParamsFromFile(str(raw_path))
    # Input/Output are graph boundaries; every remaining operation is ZG hardware.
    view = network.viewExcept(boundary)
    check(len(view.inputs()) == len(view.outputs()) == 1, "Unexpected network view")

    print("[3/6] Opening NPU:", DEVICE_URL, flush=True)
    device = xrt.Device.Open(DEVICE_URL)
    device.setWaitTime(10000)
    device_version = dict(device.version())
    print("Device version:", device_version, flush=True)

    print("[4/6] Creating ZG330 session (no Host backend)", flush=True)
    session = xrt.Session.Create([zg330backend.ZG330Backend], view, [device])
    session.apply()

    # Explicit model dtype preserves NHWC shape; standardization is NOT repeated.
    buffer = array.array("f", inputs)
    check(buffer.itemsize == 4, "Expected a 32-bit float buffer")
    tensor = xrt.Tensor(buffer, xir.TensorType(view.inputs()[0].dtype))

    print("[5/6] Running one sample on NPU", flush=True)
    started = time.perf_counter()
    outputs = session.forward([tensor])
    check(len(outputs) == 1, "Unexpected number of output tensors")
    check(outputs[0].waitForReady(timedelta(seconds=12), timedelta(milliseconds=1)),
          "NPU output readiness timed out")
    output_bytes = bytearray(17 * 4)
    outputs[0].read(output_bytes, 0, len(output_bytes))
    elapsed_ms = (time.perf_counter() - started) * 1000
    scores = list(struct.unpack("<17f", output_bytes))
    check(all(math.isfinite(v) for v in scores), "Non-finite NPU output")

    print("[6/6] Comparing NPU classification with saved ZG Host output", flush=True)
    npu_index = max(range(17), key=lambda i: scores[i])
    host_index = max(range(17), key=lambda i: reference[i])
    tied = scores.count(max(scores)) != 1
    same = npu_index == host_index
    max_error = max(abs(a - b) for a, b in zip(scores, reference))
    result = {
        "device_url": DEVICE_URL, "device_version": device_version,
        "model_json_sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
        "model_raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "input_standardized": list(inputs), "class_order": CLASSES,
        "npu_scores": scores, "host_scores": reference,
        "npu_class_index_1based": npu_index + 1, "npu_label": CLASSES[npu_index],
        "host_class_index_1based": host_index + 1, "host_label": CLASSES[host_index],
        "argmax_match": same, "npu_top_score_tied": tied,
        "max_abs_score_difference": max_error, "forward_and_read_ms": elapsed_ms,
        "scope": "one sample; NPU classification versus quantized Host reference",
    }
    result_path = base / "npu_smoke_result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    print("NPU scores:", scores, flush=True)
    print("Host scores:", reference, flush=True)
    print("NPU class: %d %s" % (npu_index + 1, CLASSES[npu_index]), flush=True)
    print("Host class: %d %s" % (host_index + 1, CLASSES[host_index]), flush=True)
    print("ARGMAX_MATCH:", same, flush=True)
    print("NPU_TOP_TIED:", tied, flush=True)
    print("MAX_ABS_SCORE_DIFFERENCE:", max_error, flush=True)
    print("FORWARD_AND_READ_MS:", elapsed_ms, flush=True)
    print("Saved:", result_path, flush=True)
    check(same and not tied, "SMOKE_FAIL: classification mismatch or NPU top-score tie")
    print("SMOKE_PASS: one NPU sample matches the ZG quantized Host class", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
