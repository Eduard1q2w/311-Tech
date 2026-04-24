import math
import threading
import time
from collections import deque

import numpy as np

from twin_state import state
import sensor_processor

SAMPLE_RATE = 20.0
CYCLE_INTERVAL = 1.0 / SAMPLE_RATE
GRAVITY = 9.81

HP_TAU_SECONDS = 5.0
FFT_BUFFER_SIZE = 256
FFT_MAX_FREQ_HZ = 50.0

NOISE_FLOOR_G = 0.005
NOISE_SILENT_SECONDS = 2.0

TORSION_BASELINE_SAMPLES = 100
BASELINE_FREQ_SECONDS = 30.0

_stop_event = threading.Event()
_thread = None
_math_lock = threading.Lock()

_prev_ax = 0.0
_prev_ay = 0.0
_prev_timestamp_ms = 0

_velocity_x_raw = 0.0
_velocity_y_raw = 0.0
_velocity_x_prev = 0.0
_velocity_y_prev = 0.0
_velocity_x_hp = 0.0
_velocity_y_hp = 0.0

_displacement_x_raw = 0.0
_displacement_y_raw = 0.0
_displacement_x_prev = 0.0
_displacement_y_prev = 0.0
_displacement_x_hp = 0.0
_displacement_y_hp = 0.0

_silent_elapsed_s = 0.0
_initialized = False

_torsion_baseline_ax = 0.0
_torsion_baseline_ay = 0.0
_torsion_baseline_count = 0
_torsion_baseline_ready = False

_ax_ring = deque(maxlen=FFT_BUFFER_SIZE)

_baseline_freq_samples = []
_baseline_freq_start_s = 0.0
_baseline_freq_locked = False
_baseline_freq_hz = 0.0


def _reset_integrators():
    global _velocity_x_raw, _velocity_y_raw
    global _velocity_x_prev, _velocity_y_prev
    global _velocity_x_hp, _velocity_y_hp
    global _displacement_x_raw, _displacement_y_raw
    global _displacement_x_prev, _displacement_y_prev
    global _displacement_x_hp, _displacement_y_hp
    global _silent_elapsed_s
    _velocity_x_raw = 0.0
    _velocity_y_raw = 0.0
    _velocity_x_prev = 0.0
    _velocity_y_prev = 0.0
    _velocity_x_hp = 0.0
    _velocity_y_hp = 0.0
    _displacement_x_raw = 0.0
    _displacement_y_raw = 0.0
    _displacement_x_prev = 0.0
    _displacement_y_prev = 0.0
    _displacement_x_hp = 0.0
    _displacement_y_hp = 0.0
    _silent_elapsed_s = 0.0


def _compute_dominant_frequency():
    if len(_ax_ring) < FFT_BUFFER_SIZE:
        return 0.0
    arr = np.array(_ax_ring, dtype=np.float64)
    arr = arr - np.mean(arr)
    window = np.hanning(FFT_BUFFER_SIZE)
    arr = arr * window
    spectrum = np.fft.rfft(arr)
    mags = np.abs(spectrum)
    if len(mags) < 2:
        return 0.0
    freqs = np.fft.rfftfreq(FFT_BUFFER_SIZE, d=1.0 / SAMPLE_RATE)
    mags[0] = 0.0
    valid = freqs <= FFT_MAX_FREQ_HZ
    if not np.any(valid):
        return 0.0
    masked = np.where(valid, mags, 0.0)
    bin_idx = int(np.argmax(masked))
    if masked[bin_idx] <= 0.0:
        return 0.0
    return float(freqs[bin_idx])


def _update_freq_baseline(current_freq_hz):
    global _baseline_freq_start_s, _baseline_freq_locked, _baseline_freq_hz
    if _baseline_freq_locked:
        return
    now = time.time()
    if _baseline_freq_start_s == 0.0:
        _baseline_freq_start_s = now
    if current_freq_hz > 0.0:
        _baseline_freq_samples.append(current_freq_hz)
    if now - _baseline_freq_start_s >= BASELINE_FREQ_SECONDS:
        if _baseline_freq_samples:
            _baseline_freq_hz = float(np.median(_baseline_freq_samples))
        else:
            _baseline_freq_hz = current_freq_hz
        _baseline_freq_locked = True
        state.update(baseline_frequency_hz=round(_baseline_freq_hz, 3))


def _update_torsion_baseline(ax, ay):
    global _torsion_baseline_ax, _torsion_baseline_ay
    global _torsion_baseline_count, _torsion_baseline_ready
    if _torsion_baseline_ready:
        return
    if abs(ax) > 0.05 or abs(ay) > 0.05:
        return
    _torsion_baseline_ax += ax
    _torsion_baseline_ay += ay
    _torsion_baseline_count += 1
    if _torsion_baseline_count >= TORSION_BASELINE_SAMPLES:
        _torsion_baseline_ax /= _torsion_baseline_count
        _torsion_baseline_ay /= _torsion_baseline_count
        _torsion_baseline_ready = True


def _compute_torsion(ax, ay):
    if not _torsion_baseline_ready:
        return 0.0
    current = math.atan2(ax, ay) if (abs(ax) + abs(ay)) > 1e-9 else 0.0
    baseline = math.atan2(_torsion_baseline_ax, _torsion_baseline_ay) if (abs(_torsion_baseline_ax) + abs(_torsion_baseline_ay)) > 1e-9 else 0.0
    diff = current - baseline
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return math.degrees(diff)


def _apply_disp_lowpass(raw_x, raw_y):
    fx = sensor_processor.disp_filter_x.step(raw_x)
    fy = sensor_processor.disp_filter_y.step(raw_y)
    return fx, fy


def _compute_cycle():
    global _prev_ax, _prev_ay, _prev_timestamp_ms
    global _velocity_x_raw, _velocity_y_raw
    global _velocity_x_prev, _velocity_y_prev
    global _velocity_x_hp, _velocity_y_hp
    global _displacement_x_raw, _displacement_y_raw
    global _displacement_x_prev, _displacement_y_prev
    global _displacement_x_hp, _displacement_y_hp
    global _silent_elapsed_s, _initialized

    with _math_lock:
        snap = state.snapshot()
        ax = snap.ax
        ay = snap.ay
        ts_ms = snap.timestamp

        _ax_ring.append(ax)
        _update_torsion_baseline(ax, ay)

        if not _initialized or _prev_timestamp_ms == 0 or ts_ms == 0:
            _prev_ax = ax
            _prev_ay = ay
            _prev_timestamp_ms = ts_ms
            _initialized = True
            _reset_integrators()
            dom = _compute_dominant_frequency()
            _update_freq_baseline(dom)
            state.update(
                sway_velocity_x=0.0,
                sway_velocity_y=0.0,
                lateral_displacement=0.0,
                torsion_angle=0.0,
                dominant_frequency=round(dom, 3),
                freq_shift_pct=0.0,
            )
            return

        dt_s = (ts_ms - _prev_timestamp_ms) / 1000.0
        if dt_s <= 0.0:
            return

        a_prev_x_ms2 = _prev_ax * GRAVITY
        a_curr_x_ms2 = ax * GRAVITY
        a_prev_y_ms2 = _prev_ay * GRAVITY
        a_curr_y_ms2 = ay * GRAVITY

        _velocity_x_prev = _velocity_x_raw
        _velocity_y_prev = _velocity_y_raw
        _velocity_x_raw += 0.5 * (a_prev_x_ms2 + a_curr_x_ms2) * dt_s
        _velocity_y_raw += 0.5 * (a_prev_y_ms2 + a_curr_y_ms2) * dt_s

        tau = HP_TAU_SECONDS
        alpha_hp = tau / (tau + dt_s)
        _velocity_x_hp = alpha_hp * _velocity_x_hp + alpha_hp * (_velocity_x_raw - _velocity_x_prev)
        _velocity_y_hp = alpha_hp * _velocity_y_hp + alpha_hp * (_velocity_y_raw - _velocity_y_prev)

        _displacement_x_prev = _displacement_x_raw
        _displacement_y_prev = _displacement_y_raw
        _displacement_x_raw += 0.5 * (_velocity_x_prev + _velocity_x_raw) * dt_s
        _displacement_y_raw += 0.5 * (_velocity_y_prev + _velocity_y_raw) * dt_s

        _displacement_x_hp = alpha_hp * _displacement_x_hp + alpha_hp * (_displacement_x_raw - _displacement_x_prev)
        _displacement_y_hp = alpha_hp * _displacement_y_hp + alpha_hp * (_displacement_y_raw - _displacement_y_prev)

        accel_mag = math.sqrt(ax * ax + ay * ay)
        if accel_mag < NOISE_FLOOR_G:
            _silent_elapsed_s += dt_s
            if _silent_elapsed_s >= NOISE_SILENT_SECONDS:
                _reset_integrators()
        else:
            _silent_elapsed_s = 0.0

        disp_fx, disp_fy = _apply_disp_lowpass(_displacement_x_hp, _displacement_y_hp)
        lateral_mm = math.sqrt(disp_fx * disp_fx + disp_fy * disp_fy) * 1000.0

        torsion_deg = _compute_torsion(ax, ay)

        dom_freq = _compute_dominant_frequency()
        _update_freq_baseline(dom_freq)
        if _baseline_freq_hz > 1e-6 and dom_freq > 0:
            shift_pct = abs(dom_freq - _baseline_freq_hz) / _baseline_freq_hz * 100.0
        else:
            shift_pct = 0.0

        state.update(
            sway_velocity_x=round(_velocity_x_hp, 5),
            sway_velocity_y=round(_velocity_y_hp, 5),
            lateral_displacement=round(lateral_mm, 2),
            torsion_angle=round(torsion_deg, 3),
            dominant_frequency=round(dom_freq, 3),
            freq_shift_pct=round(shift_pct, 2),
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
    global _prev_ax, _prev_ay, _prev_timestamp_ms, _initialized
    global _torsion_baseline_ax, _torsion_baseline_ay
    global _torsion_baseline_count, _torsion_baseline_ready
    global _baseline_freq_samples, _baseline_freq_start_s
    global _baseline_freq_locked, _baseline_freq_hz
    with _math_lock:
        _prev_ax = 0.0
        _prev_ay = 0.0
        _prev_timestamp_ms = 0
        _initialized = False
        _reset_integrators()
        _ax_ring.clear()
        _torsion_baseline_ax = 0.0
        _torsion_baseline_ay = 0.0
        _torsion_baseline_count = 0
        _torsion_baseline_ready = False
        _baseline_freq_samples = []
        _baseline_freq_start_s = 0.0
        _baseline_freq_locked = False
        _baseline_freq_hz = 0.0
        sensor_processor.disp_filter_x.reset(0.0)
        sensor_processor.disp_filter_y.reset(0.0)
    state.update(
        sway_velocity_x=0.0,
        sway_velocity_y=0.0,
        lateral_displacement=0.0,
        torsion_angle=0.0,
        dominant_frequency=0.0,
        baseline_frequency_hz=0.0,
        freq_shift_pct=0.0,
    )


if __name__ == "__main__":
    import sys

    print("=" * 58)
    print(" Durian mechanics_engine self-test")
    print("=" * 58)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    reset()
    print("\n[1] dt=0 is guarded")
    state.update(ax=0.1, ay=0.0, timestamp=1000)
    _compute_cycle()
    state.update(ax=0.2, ay=0.0, timestamp=1000)
    _compute_cycle()
    _check("no divide-by-zero raised", True)

    reset()
    print("\n[2] Velocity signal is written under sine input")
    t0 = 1000
    for i in range(80):
        state.update(ax=0.1 * math.sin(i * 0.3), ay=0.0, timestamp=t0 + i * 50)
        _compute_cycle()
    _check("|sway_velocity_x| > 0",
           abs(state.sway_velocity_x) > 0.0,
           f"(got {state.sway_velocity_x})")

    reset()
    print("\n[3] FFT with Hanning detects 2 Hz sine")
    t0 = 1000
    freq = 2.0
    for i in range(300):
        t_ms = t0 + i * 50
        t_s = t_ms / 1000.0
        ax = 0.5 * math.sin(2 * math.pi * freq * t_s)
        state.update(ax=ax, ay=0.0, timestamp=t_ms)
        _compute_cycle()
    _check("dominant_frequency near 2.0 Hz",
           abs(state.dominant_frequency - 2.0) < 0.25,
           f"(got {state.dominant_frequency})")

    reset()
    print("\n[4] Displacement finite, bounded, and resets under silence")
    t0 = 1000
    for i in range(400):
        ax = 0.05 * math.sin(i * 0.3)
        state.update(ax=ax, ay=0.0, timestamp=t0 + i * 50)
        _compute_cycle()
    _check("lateral_displacement finite",
           math.isfinite(state.lateral_displacement),
           f"(got {state.lateral_displacement} mm)")
    for i in range(400, 500):
        state.update(ax=0.0, ay=0.0, timestamp=t0 + i * 50)
        _compute_cycle()
    _check("displacement decays under silence",
           state.lateral_displacement < 1e3,
           f"(got {state.lateral_displacement} mm)")

    reset()
    print("\n[5] FFT returns 0 when buffer is not full")
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
