import math
import threading

from twin_state import state
import material_db
import stress_model

NATURAL_FREQ_HZ = 1.0
RESONANCE_BAND = 0.20
PREDICT_INTERVAL = 1.0

_stop_event = threading.Event()
_thread = None


def _compute_integrity(snap):
    score = 100.0

    if snap.stress_ratio > 0.3:
        score -= (snap.stress_ratio - 0.3) * 60.0

    score -= snap.damage_percent

    if abs(snap.torsion_angle) > 2.0:
        score -= abs(snap.torsion_angle) * 2.0

    freq = snap.dominant_frequency
    if freq > 0 and (NATURAL_FREQ_HZ * (1 - RESONANCE_BAND)) < freq < (NATURAL_FREQ_HZ * (1 + RESONANCE_BAND)):
        score -= 10.0

    return round(max(0.0, min(100.0, score)), 1)


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
    if freq <= 0:
        return False
    lower = NATURAL_FREQ_HZ * (1 - RESONANCE_BAND)
    upper = NATURAL_FREQ_HZ * (1 + RESONANCE_BAND)
    return lower < freq < upper


def _compute_damage_rate_per_hour(snap):
    mat = material_db.get_active()
    peak = max(snap.bending_stress, snap.shear_stress)
    if peak > mat.fatigue_limit and mat.ultimate_strength > 0:
        n_failure = mat.ultimate_strength / peak
        damage_per_sample = (1.0 / (n_failure * stress_model.SAMPLE_RATE)) * 100.0
        return damage_per_sample * stress_model.SAMPLE_RATE * 3600.0
    return 0.0


def _compute_ttf(snap, damage_rate_per_hour):
    if damage_rate_per_hour > 0:
        remaining = 100.0 - snap.damage_percent
        ttf = remaining / damage_rate_per_hour
        return round(min(ttf, 9999.0), 1)
    return float("inf")


def _compute_forecast(snap, damage_rate_per_hour, integrity):
    if snap.scenario_active != "none" and snap.projected_damage_rate > 0:
        effective_rate = snap.projected_damage_rate
    else:
        effective_rate = damage_rate_per_hour

    if effective_rate > 0:
        hourly_damage_pct = effective_rate
        hourly_integrity_loss = hourly_damage_pct
    else:
        hourly_integrity_loss = 0.0

    forecast = []
    for i in range(25):
        projected = integrity - (i * hourly_integrity_loss)
        forecast.append(round(max(0.0, projected), 1))
    return forecast


def _predict_cycle():
    snap = state.snapshot()

    integrity = _compute_integrity(snap)
    tier = _compute_alert_tier(integrity)
    resonance = _compute_resonance_warning(snap)
    damage_rate = _compute_damage_rate_per_hour(snap)
    ttf = _compute_ttf(snap, damage_rate)
    forecast = _compute_forecast(snap, damage_rate, integrity)

    state.update(
        integrity_score=integrity,
        alert_tier=tier,
        evacuation_flag=(tier == "evacuate"),
        resonance_warning=resonance,
        time_to_failure_hours=ttf,
        forecast_24h=forecast,
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
    state.update(
        integrity_score=100.0,
        alert_tier="nominal",
        evacuation_flag=False,
        resonance_warning=False,
        time_to_failure_hours=float("inf"),
        forecast_24h=[100.0] * 25,
    )
    stress_model.reset_damage()


def get_full_report():
    snap = state.snapshot()
    mat = material_db.get_active()
    damage_rate = _compute_damage_rate_per_hour(snap)

    report = {
        "integrity_score": snap.integrity_score,
        "alert_tier": snap.alert_tier,
        "evacuation_flag": snap.evacuation_flag,
        "resonance_warning": snap.resonance_warning,
        "material": mat.name,
        "stress_ratio": snap.stress_ratio,
        "bending_stress_mpa": snap.bending_stress,
        "shear_stress_mpa": snap.shear_stress,
        "damage_percent": snap.damage_percent,
        "fatigue_cycles": snap.fatigue_cycles,
        "damage_rate_per_hour": round(damage_rate, 6),
        "time_to_failure_hours": snap.time_to_failure_hours,
        "dominant_frequency_hz": snap.dominant_frequency,
        "natural_frequency_hz": NATURAL_FREQ_HZ,
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
    print(" predictor self-test (no hardware needed)")
    print("=" * 58)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    material_db.set_active("reinforced_concrete")

    print("\n[1] Healthy state = 100 score, nominal tier")
    state.update(
        ax=0.0, ay=0.0,
        stress_ratio=0.0, damage_percent=0.0,
        torsion_angle=0.0, dominant_frequency=0.0,
        bending_stress=0.0, shear_stress=0.0,
    )
    _predict_cycle()
    _check(
        "integrity == 100",
        state.integrity_score == 100.0,
        f"(got {state.integrity_score})",
    )
    _check(
        "tier == nominal",
        state.alert_tier == "nominal",
        f"(got '{state.alert_tier}')",
    )
    _check("no evacuation", not state.evacuation_flag)

    print("\n[2] Stress ratio > 0.3 reduces score")
    state.update(stress_ratio=0.8, damage_percent=0.0, torsion_angle=0.0, dominant_frequency=0.0)
    _predict_cycle()
    expected = 100.0 - (0.8 - 0.3) * 60.0
    _check(
        "score reduced by stress_ratio",
        abs(state.integrity_score - expected) < 0.2,
        f"(got {state.integrity_score}, expected {expected})",
    )

    print("\n[3] Damage deducted directly")
    state.update(stress_ratio=0.0, damage_percent=25.0, torsion_angle=0.0, dominant_frequency=0.0)
    _predict_cycle()
    _check(
        "score = 75",
        abs(state.integrity_score - 75.0) < 0.2,
        f"(got {state.integrity_score})",
    )

    print("\n[4] Torsion deduction")
    state.update(stress_ratio=0.0, damage_percent=0.0, torsion_angle=5.0, dominant_frequency=0.0)
    _predict_cycle()
    expected = 100.0 - 5.0 * 2.0
    _check(
        "torsion reduces score",
        abs(state.integrity_score - expected) < 0.2,
        f"(got {state.integrity_score}, expected {expected})",
    )

    print("\n[5] Resonance warning")
    state.update(stress_ratio=0.0, damage_percent=0.0, torsion_angle=0.0, dominant_frequency=1.0)
    _predict_cycle()
    _check(
        "resonance_warning = True at 1.0 Hz",
        state.resonance_warning is True,
    )
    _check(
        "score reduced by 10",
        abs(state.integrity_score - 90.0) < 0.2,
        f"(got {state.integrity_score})",
    )

    state.update(dominant_frequency=3.0)
    _predict_cycle()
    _check(
        "no resonance at 3.0 Hz",
        state.resonance_warning is False,
    )

    print("\n[6] Alert tier thresholds")
    for score_val, expected_tier in [
        (95.0, "nominal"), (70.0, "watch"), (50.0, "warning"),
        (30.0, "critical"), (10.0, "evacuate"),
    ]:
        tier = _compute_alert_tier(score_val)
        _check(
            f"score {score_val} -> {expected_tier}",
            tier == expected_tier,
            f"(got '{tier}')",
        )

    print("\n[7] Evacuation flag")
    state.update(stress_ratio=1.0, damage_percent=90.0, torsion_angle=10.0, dominant_frequency=1.0)
    _predict_cycle()
    _check(
        "evacuation_flag when score near 0",
        state.evacuation_flag is True,
        f"(tier='{state.alert_tier}', score={state.integrity_score})",
    )

    print("\n[8] Forecast is 25 elements, monotonically decreasing or flat")
    state.update(
        stress_ratio=0.5, damage_percent=5.0,
        torsion_angle=0.0, dominant_frequency=0.0,
        bending_stress=20.0, shear_stress=5.0,
        scenario_active="none",
    )
    _predict_cycle()
    fc = state.forecast_24h
    _check("forecast has 25 entries", len(fc) == 25, f"(got {len(fc)})")
    _check(
        "forecast[0] == integrity_score",
        abs(fc[0] - state.integrity_score) < 0.2,
        f"(fc[0]={fc[0]}, score={state.integrity_score})",
    )
    _check(
        "forecast non-increasing",
        all(fc[i] >= fc[i + 1] for i in range(len(fc) - 1)),
    )

    print("\n[9] reset_baseline() restores healthy state")
    reset_baseline()
    _check("score back to 100", state.integrity_score == 100.0)
    _check("tier back to nominal", state.alert_tier == "nominal")
    _check("damage reset", state.damage_percent == 0.0)

    print("\n[10] get_full_report() returns valid dict")
    state.update(ax=0.05, ay=0.02, bending_stress=5.0, shear_stress=1.0, stress_ratio=0.17)
    _predict_cycle()
    report = get_full_report()
    _check("report is dict", isinstance(report, dict))
    _check(
        "has integrity_score",
        "integrity_score" in report,
        f"(keys={list(report.keys())})",
    )
    _check(
        "has forecast_24h",
        "forecast_24h" in report and len(report["forecast_24h"]) == 25,
    )

    import json
    _check(
        "report is JSON-serialisable",
        isinstance(json.dumps(report), str),
    )

    print("\n" + "=" * 58)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
