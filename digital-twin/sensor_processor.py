import math
import queue
import threading
import time

import numpy as np
from scipy.signal import butter

import sensor_reader
from twin_state import state

CALIBRATION_SAMPLES = 50
QUEUE_GET_TIMEOUT = 1.0
CALIBRATION_TIMEOUT_S = 10.0

SAMPLE_RATE_HZ = 20.0
ACCEL_CUTOFF_HZ = 9.5
DISPLACEMENT_CUTOFF_HZ = 1.0
FILTER_ORDER = 2
TILT_DEADBAND_DEG = 0.10

_offset = {"x": 0.0, "y": 0.0, "z": 0.0}
_state_lock = threading.Lock()
_stop_event = threading.Event()
_processor_thread = None
_calibrated = threading.Event()

last_raw = {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0}


def _butter_coeffs(fs_hz, fc_hz, order):
    nyq = fs_hz * 0.5
    wn = min(max(fc_hz / nyq, 1e-4), 0.999)
    b, a = butter(order, wn, btype="low", analog=False)
    return b.tolist(), a.tolist()


_b_accel, _a_accel = _butter_coeffs(SAMPLE_RATE_HZ, ACCEL_CUTOFF_HZ, FILTER_ORDER)
_b_disp, _a_disp = _butter_coeffs(SAMPLE_RATE_HZ, DISPLACEMENT_CUTOFF_HZ, FILTER_ORDER)


class Biquad:
    def __init__(self, b, a):
        self.b = list(b)
        self.a = list(a)
        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0

    def reset(self, x0=0.0):
        self.x1 = x0
        self.x2 = x0
        self.y1 = x0
        self.y2 = x0

    def step(self, x):
        b0, b1, b2 = self.b[0], self.b[1], self.b[2]
        a1, a2 = self.a[1], self.a[2]
        y = b0 * x + b1 * self.x1 + b2 * self.x2 - a1 * self.y1 - a2 * self.y2
        self.x2 = self.x1
        self.x1 = x
        self.y2 = self.y1
        self.y1 = y
        return y


_filter_x = Biquad(_b_accel, _a_accel)
_filter_y = Biquad(_b_accel, _a_accel)
_filter_z = Biquad(_b_accel, _a_accel)
disp_filter_x = Biquad(_b_disp, _a_disp)
disp_filter_y = Biquad(_b_disp, _a_disp)


def get_disp_filter_coeffs():
    return list(_b_disp), list(_a_disp)


def get_accel_cutoff_hz():
    return ACCEL_CUTOFF_HZ


def get_sample_rate():
    return SAMPLE_RATE_HZ


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
            if val > 0.5:
                _offset[axis] = val - 1.0
            elif val < -0.5:
                _offset[axis] = val + 1.0
            else:
                _offset[axis] = val
        cal_x = new_offset["x"] - _offset["x"]
        cal_y = new_offset["y"] - _offset["y"]
        cal_z = new_offset["z"] - _offset["z"]
        _filter_x.reset(cal_x)
        _filter_y.reset(cal_y)
        _filter_z.reset(cal_z)
        disp_filter_x.reset(0.0)
        disp_filter_y.reset(0.0)
    _calibrated.set()
    return {"offset": dict(_offset), "samples": collected}


def _compute_tilt_limits():
    snap = state.snapshot()
    try:
        stories = max(1, int(snap.stories))
    except Exception:
        stories = 1
    floor_h = float(snap.floor_height) if snap.floor_height > 0 else 3.3
    H = max(0.1, stories * floor_h)
    alert_ratio = 1.0 / 500.0
    severe_ratio = 1.0 / 300.0
    critical_ratio = 1.0 / 200.0
    alert_deg = math.degrees(math.atan(alert_ratio))
    severe_deg = math.degrees(math.atan(severe_ratio))
    critical_deg = math.degrees(math.atan(critical_ratio))
    disp_limit_mm_val = H / 250.0 * 1000.0
    return alert_deg, severe_deg, critical_deg, disp_limit_mm_val, H


def _process_sample(reading):
    last_raw["x"] = reading.get("x", 0.0)
    last_raw["y"] = reading.get("y", 0.0)
    last_raw["z"] = reading.get("z", 0.0)
    last_raw["t"] = reading.get("t", time.time())

    with _state_lock:
        cal_x = last_raw["x"] - _offset["x"]
        cal_y = last_raw["y"] - _offset["y"]
        cal_z = last_raw["z"] - _offset["z"]
        fx = _filter_x.step(cal_x)
        fy = _filter_y.step(cal_y)
        fz = _filter_z.step(cal_z)

    denom_x = math.sqrt(fx * fx + fz * fz)
    denom_y = math.sqrt(fy * fy + fz * fz)
    tilt_x = math.degrees(math.atan2(fy, denom_x)) if denom_x > 1e-9 else 0.0
    tilt_y = math.degrees(math.atan2(-fx, denom_y)) if denom_y > 1e-9 else 0.0

    if abs(tilt_x) < TILT_DEADBAND_DEG:
        tilt_x = 0.0
    if abs(tilt_y) < TILT_DEADBAND_DEG:
        tilt_y = 0.0

    tilt_magnitude = math.sqrt(tilt_x * tilt_x + tilt_y * tilt_y)
    if tilt_magnitude < TILT_DEADBAND_DEG:
        tilt_magnitude = 0.0

    alert_deg, severe_deg, critical_deg, disp_limit_mm_val, _H = _compute_tilt_limits()

    state.update(
        ax=round(fx, 4),
        ay=round(fy, 4),
        az=round(fz, 4),
        tilt_x=round(tilt_x, 3),
        tilt_y=round(tilt_y, 3),
        tilt_magnitude=round(tilt_magnitude, 3),
        tilt_limit_alert_deg=round(alert_deg, 4),
        tilt_limit_severe_deg=round(severe_deg, 4),
        tilt_limit_critical_deg=round(critical_deg, 4),
        disp_limit_mm=round(disp_limit_mm_val, 2),
        timestamp=int(last_raw["t"] * 1000),
    )


def _process_loop():
    print("[sensor_processor] Durian — calibrating (50 samples)...")
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
        return {"x": _filter_x.y1, "y": _filter_y.y1, "z": _filter_z.y1}


if __name__ == "__main__":
    import sys

    print("=" * 52)
    print(" Durian sensor_processor self-test")
    print("=" * 52)

    def _reset():
        with _state_lock:
            _offset["x"] = _offset["y"] = _offset["z"] = 0.0
            _filter_x.reset(0.0)
            _filter_y.reset(0.0)
            _filter_z.reset(0.0)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    _reset()
    print("\n[1] Butterworth LPF converges to a constant DC input")
    for _ in range(400):
        _process_sample({"x": 1.0, "y": 1.0, "z": 1.0})
    fx, fy, fz = _filter_x.y1, _filter_y.y1, _filter_z.y1
    _check("x -> 1.0", abs(fx - 1.0) < 1e-3, f"(x={fx:.6f})")
    _check("y -> 1.0", abs(fy - 1.0) < 1e-3, f"(y={fy:.6f})")
    _check("z -> 1.0", abs(fz - 1.0) < 1e-3, f"(z={fz:.6f})")

    _reset()
    print("\n[2] Three-axis gravity-compensated tilt when lying flat")
    for _ in range(400):
        _process_sample({"x": 0.0, "y": 0.0, "z": 1.0})
    _check("flat: tilt_x ~ 0", abs(state.tilt_x) < 0.5, f"(tilt_x={state.tilt_x})")
    _check("flat: tilt_y ~ 0", abs(state.tilt_y) < 0.5, f"(tilt_y={state.tilt_y})")
    _check("flat: tilt_mag ~ 0", state.tilt_magnitude < 0.5, f"(mag={state.tilt_magnitude})")

    _reset()
    print("\n[3] y=1, z=0 -> tilt_x ~ +90")
    for _ in range(800):
        _process_sample({"x": 0.0, "y": 1.0, "z": 0.0})
    _check("tilt_x ~ 90", abs(abs(state.tilt_x) - 90.0) < 1.0, f"(tilt_x={state.tilt_x})")

    _reset()
    print("\n[4] x=1, z=0 -> tilt_y ~ -90 (per sign convention)")
    for _ in range(800):
        _process_sample({"x": 1.0, "y": 0.0, "z": 0.0})
    _check("|tilt_y| ~ 90", abs(abs(state.tilt_y) - 90.0) < 1.0, f"(tilt_y={state.tilt_y})")

    _reset()
    print("\n[5] Tilt limits derived from geometry")
    state.update(stories=10, floor_height=3.0)
    _process_sample({"x": 0.0, "y": 0.0, "z": 1.0})
    _check("limit alert > 0", state.tilt_limit_alert_deg > 0)
    _check("severe > alert", state.tilt_limit_severe_deg > state.tilt_limit_alert_deg)
    _check("critical > severe", state.tilt_limit_critical_deg > state.tilt_limit_severe_deg)

    print("\n" + "=" * 52)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
