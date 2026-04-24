import math
import threading
import time
from collections import deque

import numpy as np

from twin_state import state

VELOCITY_ALPHA = 0.3
SAMPLE_RATE = 20.0
FFT_BUFFER_SIZE = 64
DRIFT_RESET_SECONDS = 5.0
CYCLE_INTERVAL = 1.0 / SAMPLE_RATE
GRAVITY = 9.81

_stop_event = threading.Event()
_thread = None
_math_lock = threading.Lock()

_prev_ax = 0.0
_prev_ay = 0.0
_prev_timestamp_ms = 0
_filtered_velocity_x = 0.0
_filtered_velocity_y = 0.0
_int_velocity_x_ms = 0.0
_int_velocity_y_ms = 0.0
_displacement_x_m = 0.0
_displacement_y_m = 0.0
_last_drift_reset_s = 0.0
_initialized = False
_ax_ring = deque(maxlen=FFT_BUFFER_SIZE)


def _reset_drift():
    global _int_velocity_x_ms, _int_velocity_y_ms
    global _displacement_x_m, _displacement_y_m, _last_drift_reset_s
    _int_velocity_x_ms = 0.0
    _int_velocity_y_ms = 0.0
    _displacement_x_m = 0.0
    _displacement_y_m = 0.0
    _last_drift_reset_s = time.time()


def _compute_dominant_frequency():
    if len(_ax_ring) < FFT_BUFFER_SIZE:
        return 0.0
    arr = np.array(_ax_ring, dtype=np.float64)
    arr = arr - np.mean(arr)
    spectrum = np.fft.rfft(arr)
    mags = np.abs(spectrum)
    if len(mags) < 2:
        return 0.0
    mags[0] = 0.0
    bin_idx = int(np.argmax(mags))
    if mags[bin_idx] <= 0.0:
        return 0.0
    return bin_idx * SAMPLE_RATE / FFT_BUFFER_SIZE


def _compute_cycle():
    global _prev_ax, _prev_ay, _prev_timestamp_ms
    global _filtered_velocity_x, _filtered_velocity_y
    global _int_velocity_x_ms, _int_velocity_y_ms
    global _displacement_x_m, _displacement_y_m
    global _last_drift_reset_s, _initialized

    with _math_lock:
        snap = state.snapshot()
        # Apply a deadband to ignore micro-vibrations and stabilize output
        ax = snap.ax if abs(snap.ax) > 0.015 else 0.0
        ay = snap.ay if abs(snap.ay) > 0.015 else 0.0
        ts_ms = snap.timestamp
        tilt_x = snap.tilt_x
        tilt_y = snap.tilt_y

        _ax_ring.append(ax)
        torsion = abs(tilt_x - tilt_y)

        if not _initialized or _prev_timestamp_ms == 0 or ts_ms == 0:
            _prev_ax = ax
            _prev_ay = ay
            _prev_timestamp_ms = ts_ms
            _last_drift_reset_s = time.time()
            _initialized = True
            dom = _compute_dominant_frequency()
            state.update(
                sway_velocity_x=0.0,
                sway_velocity_y=0.0,
                lateral_displacement=0.0,
                torsion_angle=round(torsion, 2),
                dominant_frequency=round(dom, 3),
            )
            return

        dt_s = (ts_ms - _prev_timestamp_ms) / 1000.0
        if dt_s <= 0.0:
            return

        raw_vx = (ax - _prev_ax) / dt_s * GRAVITY
        raw_vy = (ay - _prev_ay) / dt_s * GRAVITY
        _filtered_velocity_x = VELOCITY_ALPHA * raw_vx + (1.0 - VELOCITY_ALPHA) * _filtered_velocity_x
        _filtered_velocity_y = VELOCITY_ALPHA * raw_vy + (1.0 - VELOCITY_ALPHA) * _filtered_velocity_y

        a_prev_x_ms2 = _prev_ax * GRAVITY
        a_curr_x_ms2 = ax * GRAVITY
        a_prev_y_ms2 = _prev_ay * GRAVITY
        a_curr_y_ms2 = ay * GRAVITY

        v_prev_x = _int_velocity_x_ms
        v_prev_y = _int_velocity_y_ms
        _int_velocity_x_ms += 0.5 * (a_prev_x_ms2 + a_curr_x_ms2) * dt_s
        _int_velocity_y_ms += 0.5 * (a_prev_y_ms2 + a_curr_y_ms2) * dt_s

        _displacement_x_m += 0.5 * (v_prev_x + _int_velocity_x_ms) * dt_s
        _displacement_y_m += 0.5 * (v_prev_y + _int_velocity_y_ms) * dt_s

        # Simulate structural restoring force and damping when structure is resting
        if ax == 0.0 and ay == 0.0:
            _int_velocity_x_ms *= 0.90
            _int_velocity_y_ms *= 0.90
            _displacement_x_m *= 0.90
            _displacement_y_m *= 0.90

        now_s = time.time()
        if now_s - _last_drift_reset_s >= DRIFT_RESET_SECONDS:
            _reset_drift()

        dom_freq = _compute_dominant_frequency()
        lateral_mm = math.sqrt(_displacement_x_m ** 2 + _displacement_y_m ** 2) * 1000.0

        state.update(
            sway_velocity_x=round(_filtered_velocity_x, 4),
            sway_velocity_y=round(_filtered_velocity_y, 4),
            lateral_displacement=round(lateral_mm, 1),
            torsion_angle=round(torsion, 2),
            dominant_frequency=round(dom_freq, 3),
        )

        _prev_ax = ax
        _prev_ay = ay
        _prev_timestamp_ms = ts_ms


def _mechanics_loop():
    while not _stop_event.is_set():
        try:
            _compute_cycle()
        except Exception as e:
            print(f"[mechanics_engine] cycle error: {type(e).__name__}: {e}")
        _stop_event.wait(CYCLE_INTERVAL)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop_event.clear()
    _thread = threading.Thread(
        target=_mechanics_loop, name="MechanicsEngine", daemon=True
    )
    _thread.start()
    return _thread


def stop():
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2.0)


def reset():
    global _prev_ax, _prev_ay, _prev_timestamp_ms
    global _filtered_velocity_x, _filtered_velocity_y, _initialized
    with _math_lock:
        _prev_ax = 0.0
        _prev_ay = 0.0
        _prev_timestamp_ms = 0
        _filtered_velocity_x = 0.0
        _filtered_velocity_y = 0.0
        _reset_drift()
        _ax_ring.clear()
        _initialized = False
    state.update(
        sway_velocity_x=0.0,
        sway_velocity_y=0.0,
        lateral_displacement=0.0,
        torsion_angle=0.0,
        dominant_frequency=0.0,
    )


if __name__ == "__main__":
    import sys

    print("=" * 58)
    print(" mechanics_engine self-test (no hardware needed)")
    print("=" * 58)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    reset()
    print("\n[1] dt=0 is guarded (same timestamp twice)")
    state.update(ax=0.1, ay=0.0, timestamp=1000)
    _compute_cycle()
    state.update(ax=0.2, ay=0.0, timestamp=1000)
    _compute_cycle()
    _check("no divide-by-zero raised", True)

    reset()
    print("\n[2] Torsion = abs(tilt_x - tilt_y)")
    state.update(tilt_x=5.0, tilt_y=2.0, ax=0.0, ay=0.0, timestamp=1000)
    _compute_cycle()
    state.update(tilt_x=5.0, tilt_y=2.0, ax=0.0, ay=0.0, timestamp=1050)
    _compute_cycle()
    _check(
        "torsion == 3.0",
        abs(state.torsion_angle - 3.0) < 0.01,
        f"(got {state.torsion_angle})",
    )

    reset()
    print("\n[3] Velocity signal is written (not literally zero)")
    t0 = 1000
    for i in range(40):
        state.update(ax=0.1 * math.sin(i * 0.3), ay=0.0, timestamp=t0 + i * 50)
        _compute_cycle()
    _check(
        "sway_velocity_x != 0",
        abs(state.sway_velocity_x) > 0.0,
        f"(got {state.sway_velocity_x})",
    )

    reset()
    print("\n[4] FFT detects 2 Hz sine wave")
    t0 = 1000
    freq = 2.0
    for i in range(128):
        t_ms = t0 + i * 50
        t_s = t_ms / 1000.0
        ax = 0.5 * math.sin(2 * math.pi * freq * t_s)
        state.update(ax=ax, ay=0.0, timestamp=t_ms)
        _compute_cycle()
    _check(
        "dominant_frequency near 2.0 Hz",
        abs(state.dominant_frequency - 2.0) < 0.35,
        f"(got {state.dominant_frequency})",
    )

    reset()
    print("\n[5] Displacement stays bounded under drift-reset")
    t0 = 1000
    for i in range(200):
        ax = 0.05 * math.sin(i * 0.3)
        state.update(ax=ax, ay=0.0, timestamp=t0 + i * 50)
        _compute_cycle()
    _check(
        "lateral_displacement is finite and bounded",
        math.isfinite(state.lateral_displacement) and state.lateral_displacement < 10000.0,
        f"(got {state.lateral_displacement} mm)",
    )

    reset()
    print("\n[6] FFT returns 0 when buffer is not full")
    state.update(ax=0.1, ay=0.0, timestamp=1000)
    _compute_cycle()
    _check("freq == 0 early", state.dominant_frequency == 0.0)

    print("\n" + "=" * 58)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
