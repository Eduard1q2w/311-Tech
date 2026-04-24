import math
import queue
import threading
import time

import sensor_reader
from twin_state import state

ALPHA = 0.2
CALIBRATION_SAMPLES = 50
QUEUE_GET_TIMEOUT = 1.0
CALIBRATION_TIMEOUT_S = 10.0

_offset = {"x": 0.0, "y": 0.0, "z": 0.0}
_filtered = {"x": 0.0, "y": 0.0, "z": 0.0}
_state_lock = threading.Lock()
_stop_event = threading.Event()
_processor_thread = None
_calibrated = threading.Event()

last_raw = {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0}


def _collect_samples(n, timeout_s=CALIBRATION_TIMEOUT_S):
    totals = {"x": 0.0, "y": 0.0, "z": 0.0}
    count = 0
    deadline = time.time() + timeout_s
    while count < n and time.time() < deadline:
        try:
            reading = sensor_reader.data_queue.get(timeout=QUEUE_GET_TIMEOUT)
        except queue.Empty:
            continue
        totals["x"] += reading["x"]
        totals["y"] += reading["y"]
        totals["z"] += reading["z"]
        count += 1
    if count == 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0}, 0
    return {k: v / count for k, v in totals.items()}, count


def recalibrate(samples=CALIBRATION_SAMPLES):
    new_offset, collected = _collect_samples(samples)
    with _state_lock:
        for axis in ["x", "y", "z"]:
            val = new_offset[axis]
            # MPU6050 reads 1g on the vertical axis. We want to calibrate to 0 tilt,
            # meaning we expect 1g (or -1g) on the dominant vertical axis.
            if val > 0.5:
                _offset[axis] = val - 1.0
            elif val < -0.5:
                _offset[axis] = val + 1.0
            else:
                _offset[axis] = val
            # Initialize filter to the calibrated baseline
            _filtered[axis] = new_offset[axis] - _offset[axis]
    _calibrated.set()
    return {"offset": dict(_offset), "samples": collected}


def _process_sample(reading):
    last_raw["x"] = reading.get("x", 0.0)
    last_raw["y"] = reading.get("y", 0.0)
    last_raw["z"] = reading.get("z", 0.0)
    last_raw["t"] = reading.get("t", time.time())

    with _state_lock:
        cal_x = last_raw["x"] - _offset["x"]
        cal_y = last_raw["y"] - _offset["y"]
        cal_z = last_raw["z"] - _offset["z"]
        _filtered["x"] = ALPHA * cal_x + (1.0 - ALPHA) * _filtered["x"]
        _filtered["y"] = ALPHA * cal_y + (1.0 - ALPHA) * _filtered["y"]
        _filtered["z"] = ALPHA * cal_z + (1.0 - ALPHA) * _filtered["z"]
        fx = _filtered["x"]
        fy = _filtered["y"]
        fz = _filtered["z"]

    tilt_x = round(math.atan2(fy, fz) * 180.0 / math.pi, 2)
    tilt_y = round(math.atan2(fx, fz) * 180.0 / math.pi, 2)

    # Deadband to make it "less sensible" when nearly stationary and upright
    if abs(tilt_x) < 0.5:
        tilt_x = 0.0
    if abs(tilt_y) < 0.5:
        tilt_y = 0.0

    state.update(
        ax=round(fx, 4),
        ay=round(fy, 4),
        az=round(fz, 4),
        tilt_x=tilt_x,
        tilt_y=tilt_y,
        timestamp=int(last_raw["t"] * 1000),
    )


def _process_loop():
    print("[sensor_processor] calibrating (50 samples)...")
    try:
        result = recalibrate()
        print(
            "[sensor_processor] offset set to x={x:+.4f}  y={y:+.4f}  z={z:+.4f}  (n={n})".format(
                n=result["samples"], **result["offset"]
            )
        )
    except Exception as e:
        print(f"[sensor_processor] calibration error: {type(e).__name__}: {e}")
    while not _stop_event.is_set():
        try:
            reading = sensor_reader.data_queue.get(timeout=QUEUE_GET_TIMEOUT)
        except queue.Empty:
            continue
        try:
            _process_sample(reading)
        except Exception as e:
            print(f"[sensor_processor] sample error: {type(e).__name__}: {e}")


def start():
    global _processor_thread
    if _processor_thread is not None and _processor_thread.is_alive():
        return _processor_thread
    _stop_event.clear()
    _processor_thread = threading.Thread(
        target=_process_loop, name="SensorProcessor", daemon=True
    )
    _processor_thread.start()
    return _processor_thread


def stop():
    _stop_event.set()
    if _processor_thread is not None:
        _processor_thread.join(timeout=2.0)


def is_calibrated():
    return _calibrated.is_set()


def get_offset():
    with _state_lock:
        return dict(_offset)


def get_filtered():
    with _state_lock:
        return dict(_filtered)


if __name__ == "__main__":
    import sys

    print("=" * 52)
    print(" sensor_processor self-test (no hardware needed)")
    print("=" * 52)

    def _reset():
        with _state_lock:
            _offset["x"] = _offset["y"] = _offset["z"] = 0.0
            _filtered["x"] = _filtered["y"] = _filtered["z"] = 0.0

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    _reset()
    print("\n[1] EMA filter converges to a constant input")
    for _ in range(100):
        _process_sample({"x": 1.0, "y": 1.0, "z": 1.0})
    fx, fy, fz = _filtered["x"], _filtered["y"], _filtered["z"]
    _check(
        "x converges to 1.0",
        abs(fx - 1.0) < 1e-4,
        f"(x={fx:.6f})",
    )
    _check(
        "y converges to 1.0",
        abs(fy - 1.0) < 1e-4,
        f"(y={fy:.6f})",
    )
    _check(
        "z converges to 1.0",
        abs(fz - 1.0) < 1e-4,
        f"(z={fz:.6f})",
    )

    _reset()
    print("\n[2] Single-sample outlier is attenuated by (1 - alpha)")
    _process_sample({"x": 10.0, "y": 0.0, "z": 1.0})
    _check(
        "first sample = alpha * raw",
        abs(_filtered["x"] - 2.0) < 1e-6,
        f"(x={_filtered['x']:.4f}, expected 2.0)",
    )

    _reset()
    print("\n[3] Step response reaches 95% within 1/alpha * 3 samples")
    reached = None
    for i in range(1, 101):
        _process_sample({"x": 1.0, "y": 0.0, "z": 1.0})
        if _filtered["x"] >= 0.95 and reached is None:
            reached = i
    _check(
        "95% reached before sample 20",
        reached is not None and reached < 20,
        f"(reached at sample {reached})",
    )

    _reset()
    print("\n[4] Calibration offset is subtracted before filtering")
    with _state_lock:
        _offset["x"] = 0.5
    _process_sample({"x": 1.5, "y": 0.0, "z": 1.0})
    _check(
        "offset removes bias",
        abs(_filtered["x"] - 0.2) < 1e-6,
        f"(x={_filtered['x']:.4f}, expected 0.2)",
    )

    _reset()
    print("\n[5] Tilt angles")
    for _ in range(200):
        _process_sample({"x": 0.0, "y": 0.0, "z": 1.0})
    _check(
        "flat: tilt_x ~ 0",
        abs(state.tilt_x) < 0.5,
        f"(tilt_x={state.tilt_x})",
    )
    _check(
        "flat: tilt_y ~ 0",
        abs(state.tilt_y) < 0.5,
        f"(tilt_y={state.tilt_y})",
    )

    _reset()
    for _ in range(400):
        _process_sample({"x": 0.0, "y": 1.0, "z": 0.0})
    _check(
        "y=1,z=0: tilt_x ~ 90 deg",
        abs(abs(state.tilt_x) - 90.0) < 1.0,
        f"(tilt_x={state.tilt_x})",
    )

    _reset()
    for _ in range(400):
        _process_sample({"x": 1.0, "y": 0.0, "z": 0.0})
    _check(
        "x=1,z=0: tilt_y ~ 90 deg",
        abs(abs(state.tilt_y) - 90.0) < 1.0,
        f"(tilt_y={state.tilt_y})",
    )

    _reset()
    print("\n[6] twin_state is updated atomically and serialises")
    _process_sample({"x": 0.25, "y": -0.1, "z": 0.98, "t": 1_700_000_000.0})
    snap = state.to_dict()
    _check(
        "ax is filtered value, not raw",
        abs(snap["ax"] - 0.05) < 1e-6,
        f"(ax={snap['ax']})",
    )
    _check(
        "timestamp is ms",
        snap["timestamp"] == 1_700_000_000_000,
        f"(ts={snap['timestamp']})",
    )
    import json

    _check(
        "snapshot JSON-serialisable",
        isinstance(json.dumps(snap), str),
    )

    print("\n" + "=" * 52)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
