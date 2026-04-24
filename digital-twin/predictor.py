import math
import threading
import time
from collections import deque

from twin_state import state
import material_db
import stress_model

NATURAL_FREQ_HZ = 1.0
RESONANCE_BAND = 0.20
PREDICT_INTERVAL = 1.0

W_FREQ = 0.20
W_TILT = 0.15
FREQ_SHIFT_NORMALIZATION_PCT = 20.0
TTF_HISTORY_SECONDS = 60.0

_stop_event = threading.Event()
_thread = None

_history_lock = threading.Lock()
_damage_history = deque()


def _record_damage_sample(now_s, damage_frac):
    _damage_history.append((now_s, damage_frac))
    cutoff = now_s - TTF_HISTORY_SECONDS * 2.0
    while _damage_history and _damage_history[0][0] < cutoff:
        _damage_history.popleft()


def _get_damage_rate_per_second(now_s, damage_now):
    if not _damage_history:
        return 0.0
    target = now_s - TTF_HISTORY_SECONDS
    past_sample = None
    for ts, val in _damage_history:
        if ts <= target:
            past_sample = (ts, val)
        else:
            break
    if past_sample is None:
        past_sample = _damage_history[0]
    dt = now_s - past_sample[0]
    if dt <= 0:
        return 0.0
    return max(0.0, (damage_now - past_sample[1]) / dt)


def _compute_alert_tier(score):
    if score >= 80:
        return "nominal"
    if score >= 60:
        return "watch"
    if score >= 40:
        return "warning"
    if score >= 20:
        return "critical"
    return "evacuate"


def _compute_resonance_warning(snap):
    freq = snap.dominant_frequency
    baseline = snap.baseline_frequency_hz if snap.baseline_frequency_hz > 0 else NATURAL_FREQ_HZ
    if freq <= 0:
        return False
    lower = baseline * (1 - RESONANCE_BAND)
    upper = baseline * (1 + RESONANCE_BAND)
    return lower < freq < upper


def _tilt_critical_deg(snap):
    crit = float(snap.tilt_limit_critical_deg)
    if crit > 0:
        return crit
    try:
        stories = max(1, int(snap.stories))
    except Exception:
        stories = 1
    floor_h = float(snap.floor_height) if snap.floor_height > 0 else 3.3
    H = max(0.1, stories * floor_h)
    return math.degrees(math.atan((1.0 / 200.0)))


def _disp_limit_mm(snap):
    lim = float(snap.disp_limit_mm)
    if lim > 0:
        return lim
    try:
        stories = max(1, int(snap.stories))
    except Exception:
        stories = 1
    floor_h = float(snap.floor_height) if snap.floor_height > 0 else 3.3
    H = max(0.1, stories * floor_h)
    return H / 250.0 * 1000.0


def _compute_integrity(snap):
    mat = material_db.get_active()

    w_stress = float(getattr(mat, "stress_weight", 0.35))
    w_fatigue = float(getattr(mat, "fatigue_weight", 0.20))
    w_disp = float(getattr(mat, "disp_weight", 0.10))
    w_freq = W_FREQ
    w_tilt = W_TILT

    stress_ratio = max(0.0, min(1.0, float(snap.stress_ratio)))
    cumulative_damage_frac = stress_model.get_cumulative_damage_fraction()
    cumulative_damage = max(0.0, min(1.0, cumulative_damage_frac))
    freq_shift_pct = max(0.0, float(snap.freq_shift_pct))
    tilt_magnitude = max(0.0, float(snap.tilt_magnitude))
    tilt_critical = max(1e-6, _tilt_critical_deg(snap))
    displacement_mm = max(0.0, float(snap.lateral_displacement))
    disp_limit_mm = max(1e-6, _disp_limit_mm(snap))

    penalty_stress = min(stress_ratio, 1.0) * 100.0 * w_stress
    penalty_fatigue = min(cumulative_damage, 1.0) * 100.0 * w_fatigue
    penalty_freq = min(freq_shift_pct / FREQ_SHIFT_NORMALIZATION_PCT, 1.0) * 100.0 * w_freq
    penalty_tilt = min(tilt_magnitude / tilt_critical, 1.0) * 100.0 * w_tilt
    penalty_disp = min(displacement_mm / disp_limit_mm, 1.0) * 100.0 * w_disp

    integrity = 100.0 - penalty_stress - penalty_fatigue - penalty_freq - penalty_tilt - penalty_disp
    integrity = max(0.0, min(100.0, integrity))

    return {
        "integrity": round(integrity, 1),
        "penalty_stress": round(penalty_stress, 2),
        "penalty_fatigue": round(penalty_fatigue, 2),
        "penalty_freq": round(penalty_freq, 2),
        "penalty_tilt": round(penalty_tilt, 2),
        "penalty_disp": round(penalty_disp, 2),
        "w_stress": w_stress,
        "w_fatigue": w_fatigue,
        "w_freq": w_freq,
        "w_tilt": w_tilt,
        "w_disp": w_disp,
    }


def _compute_ttf_seconds(damage_frac_now, rate_per_second):
    if rate_per_second <= 0:
        return float("inf")
    remaining = max(0.0, 1.0 - damage_frac_now)
    if remaining <= 0:
        return 0.0
    return remaining / rate_per_second


def _compute_forecast(integrity_now, rate_per_second):
    forecast = []
    loss_per_hour = rate_per_second * 3600.0 * 100.0
    for i in range(25):
        projected = integrity_now - i * loss_per_hour
        forecast.append(round(max(0.0, projected), 1))
    return forecast


def _predict_cycle():
    snap = state.snapshot()
    now_s = time.time()

    damage_frac = stress_model.get_cumulative_damage_fraction()
    with _history_lock:
        _record_damage_sample(now_s, damage_frac)
        rate_per_second = _get_damage_rate_per_second(now_s, damage_frac)

    breakdown = _compute_integrity(snap)
    integrity = breakdown["integrity"]
    tier = _compute_alert_tier(integrity)
    resonance = _compute_resonance_warning(snap)

    if snap.scenario_active != "none" and snap.projected_damage_rate > 0:
        effective_rate_per_hour = snap.projected_damage_rate
        effective_rate_per_second = effective_rate_per_hour / 3600.0 / 100.0
    else:
        effective_rate_per_second = rate_per_second

    ttf_s = _compute_ttf_seconds(damage_frac, effective_rate_per_second)
    if math.isinf(ttf_s):
        ttf_hours = float("inf")
    else:
        ttf_hours = ttf_s / 3600.0

    forecast = _compute_forecast(integrity, effective_rate_per_second)

    state.update(
        integrity_score=integrity,
        alert_tier=tier,
        evacuation_flag=(tier == "evacuate"),
        resonance_warning=resonance,
        time_to_failure_hours=round(ttf_hours, 2) if math.isfinite(ttf_hours) else float("inf"),
        forecast_24h=forecast,
        penalty_stress=breakdown["penalty_stress"],
        penalty_fatigue=breakdown["penalty_fatigue"],
        penalty_freq=breakdown["penalty_freq"],
        penalty_tilt=breakdown["penalty_tilt"],
        penalty_disp=breakdown["penalty_disp"],
        w_stress=breakdown["w_stress"],
        w_fatigue=breakdown["w_fatigue"],
        w_freq=breakdown["w_freq"],
        w_tilt=breakdown["w_tilt"],
        w_disp=breakdown["w_disp"],
    )


def _predict_loop():
    while not _stop_event.is_set():
        try:
            _predict_cycle()
        except Exception as e:
            print(f"[predictor] cycle error: {type(e).__name__}: {e}")
        _stop_event.wait(PREDICT_INTERVAL)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop_event.clear()
    _thread = threading.Thread(
        target=_predict_loop, name="Predictor", daemon=True
    )
    _thread.start()
    return _thread


def stop():
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2.0)


def reset_baseline():
    with _history_lock:
        _damage_history.clear()
    state.update(
        integrity_score=100.0,
        alert_tier="nominal",
        evacuation_flag=False,
        resonance_warning=False,
        time_to_failure_hours=float("inf"),
        forecast_24h=[100.0] * 25,
        penalty_stress=0.0,
        penalty_fatigue=0.0,
        penalty_freq=0.0,
        penalty_tilt=0.0,
        penalty_disp=0.0,
    )
    stress_model.reset_damage()


def get_full_report():
    snap = state.snapshot()
    mat = material_db.get_active()
    damage_frac = stress_model.get_cumulative_damage_fraction()
    with _history_lock:
        rate_per_second = _get_damage_rate_per_second(time.time(), damage_frac)

    report = {
        "integrity_score": snap.integrity_score,
        "alert_tier": snap.alert_tier,
        "evacuation_flag": snap.evacuation_flag,
        "resonance_warning": snap.resonance_warning,
        "material": mat.name,
        "structural_system": snap.structural_system,
        "stress_ratio": snap.stress_ratio,
        "bending_stress_mpa": snap.bending_stress,
        "shear_stress_mpa": snap.shear_stress,
        "damage_percent": snap.damage_percent,
        "fatigue_cycles": snap.fatigue_cycles,
        "damage_rate_per_hour": round(rate_per_second * 3600.0 * 100.0, 6),
        "time_to_failure_hours": snap.time_to_failure_hours,
        "dominant_frequency_hz": snap.dominant_frequency,
        "baseline_frequency_hz": snap.baseline_frequency_hz,
        "freq_shift_pct": snap.freq_shift_pct,
        "natural_frequency_hz": NATURAL_FREQ_HZ,
        "tilt_magnitude_deg": snap.tilt_magnitude,
        "tilt_limit_critical_deg": snap.tilt_limit_critical_deg,
        "displacement_mm": snap.lateral_displacement,
        "disp_limit_mm": snap.disp_limit_mm,
        "penalty_stress": snap.penalty_stress,
        "penalty_fatigue": snap.penalty_fatigue,
        "penalty_freq": snap.penalty_freq,
        "penalty_tilt": snap.penalty_tilt,
        "penalty_disp": snap.penalty_disp,
        "w_stress": snap.w_stress,
        "w_fatigue": snap.w_fatigue,
        "w_freq": snap.w_freq,
        "w_tilt": snap.w_tilt,
        "w_disp": snap.w_disp,
        "scenario_active": snap.scenario_active,
        "projected_stress_mpa": snap.projected_stress,
        "forecast_24h": snap.forecast_24h,
    }

    if math.isinf(report["time_to_failure_hours"]):
        report["time_to_failure_hours"] = None

    return report


if __name__ == "__main__":
    import sys

    print("=" * 58)
    print(" Durian predictor self-test")
    print("=" * 58)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    material_db.set_active("reinforced_concrete")
    state.update(stories=3, floor_height=3.3, plan_width=10.0, plan_depth=10.0)

    print("\n[1] Healthy state = 100, nominal tier")
    reset_baseline()
    state.update(
        ax=0.0, ay=0.0,
        stress_ratio=0.0, damage_percent=0.0,
        tilt_magnitude=0.0, lateral_displacement=0.0,
        freq_shift_pct=0.0, dominant_frequency=0.0,
        tilt_limit_critical_deg=0.3, disp_limit_mm=40.0,
    )
    stress_model.reset_damage()
    _predict_cycle()
    _check("integrity == 100", state.integrity_score == 100.0,
           f"(got {state.integrity_score})")
    _check("tier == nominal", state.alert_tier == "nominal",
           f"(got '{state.alert_tier}')")
    _check("no evacuation", not state.evacuation_flag)

    print("\n[2] Stress ratio drops score by weighted penalty")
    reset_baseline()
    state.update(stress_ratio=0.5, tilt_magnitude=0.0, lateral_displacement=0.0,
                 freq_shift_pct=0.0, dominant_frequency=0.0,
                 tilt_limit_critical_deg=0.3, disp_limit_mm=40.0)
    stress_model.reset_damage()
    _predict_cycle()
    mat = material_db.get_active()
    expected = 100.0 - (0.5 * 100.0 * mat.stress_weight)
    _check("score drops by stress penalty",
           abs(state.integrity_score - expected) < 0.5,
           f"(got {state.integrity_score}, expected {expected:.2f})")

    print("\n[3] Forecast is 25 elements, non-increasing")
    _predict_cycle()
    fc = state.forecast_24h
    _check("25 elements", len(fc) == 25, f"(got {len(fc)})")
    _check("non-increasing", all(fc[i] >= fc[i + 1] for i in range(len(fc) - 1)))

    print("\n[4] Alert tier thresholds")
    for score_val, expected_tier in [
        (95.0, "nominal"), (70.0, "watch"), (50.0, "warning"),
        (30.0, "critical"), (10.0, "evacuate"),
    ]:
        tier = _compute_alert_tier(score_val)
        _check(f"score {score_val} -> {expected_tier}", tier == expected_tier,
               f"(got '{tier}')")

    print("\n[5] get_full_report() has weight fields")
    report = get_full_report()
    for key in ["w_stress", "w_fatigue", "w_freq", "w_tilt", "w_disp",
                "penalty_stress", "penalty_fatigue", "penalty_freq",
                "penalty_tilt", "penalty_disp", "baseline_frequency_hz",
                "freq_shift_pct"]:
        _check(f"report has '{key}'", key in report)

    print("\n" + "=" * 58)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
