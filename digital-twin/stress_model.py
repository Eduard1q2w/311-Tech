import math
import threading
import time

from twin_state import state
import material_db

BUILDING_HEIGHT = 10.0
CROSS_SECTION_WIDTH = 0.3
CROSS_SECTION_DEPTH = 0.3
WALL_THICKNESS = 0.05

MASS_ESTIMATE = 5000.0
SAMPLE_RATE = 20.0
CYCLE_INTERVAL = 1.0 / SAMPLE_RATE

I = (CROSS_SECTION_WIDTH * CROSS_SECTION_DEPTH ** 3) / 12.0
C = CROSS_SECTION_DEPTH / 2.0
AREA = CROSS_SECTION_WIDTH * CROSS_SECTION_DEPTH

_stop_event = threading.Event()
_thread = None
_damage_lock = threading.Lock()
_cumulative_damage = 0.0
_total_cycles = 0


def _compute_cycle():
    global _cumulative_damage, _total_cycles

    snap = state.snapshot()
    mat = material_db.get_active()

    accel_x = snap.ax * 9.81
    accel_y = snap.ay * 9.81
    lateral_accel = math.sqrt(accel_x ** 2 + accel_y ** 2)

    force = MASS_ESTIMATE * lateral_accel
    moment = force * BUILDING_HEIGHT

    sigma_bending = (moment * C / I) / 1e6
    tau_shear = (1.5 * force / AREA) / 1e6

    peak_stress = max(sigma_bending, tau_shear)
    ratio = peak_stress / mat.yield_strength if mat.yield_strength > 0 else 0.0
    ratio = max(0.0, min(1.0, ratio))

    with _damage_lock:
        if peak_stress > mat.fatigue_limit and mat.ultimate_strength > 0:
            n_failure = mat.ultimate_strength / peak_stress
            damage_increment = 1.0 / (n_failure * SAMPLE_RATE)
            _cumulative_damage += damage_increment * 100.0
            _cumulative_damage = min(_cumulative_damage, 100.0)
        _total_cycles += 1
        damage_pct = _cumulative_damage
        cycles = _total_cycles

    state.update(
        bending_stress=round(sigma_bending, 4),
        shear_stress=round(tau_shear, 4),
        stress_ratio=round(ratio, 4),
        damage_percent=round(damage_pct, 6),
        fatigue_cycles=cycles,
    )


def _stress_loop():
    while not _stop_event.is_set():
        try:
            _compute_cycle()
        except Exception as e:
            print(f"[stress_model] cycle error: {type(e).__name__}: {e}")
        _stop_event.wait(CYCLE_INTERVAL)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop_event.clear()
    _thread = threading.Thread(
        target=_stress_loop, name="StressModel", daemon=True
    )
    _thread.start()
    return _thread


def stop():
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2.0)


def reset_damage():
    global _cumulative_damage, _total_cycles
    with _damage_lock:
        _cumulative_damage = 0.0
        _total_cycles = 0
    state.update(damage_percent=0.0, fatigue_cycles=0)


def get_damage_report():
    snap = state.snapshot()
    mat = material_db.get_active()
    with _damage_lock:
        damage = _cumulative_damage
        cycles = _total_cycles
    return {
        "material": mat.name,
        "yield_strength_mpa": mat.yield_strength,
        "ultimate_strength_mpa": mat.ultimate_strength,
        "fatigue_limit_mpa": mat.fatigue_limit,
        "bending_stress_mpa": snap.bending_stress,
        "shear_stress_mpa": snap.shear_stress,
        "stress_ratio": snap.stress_ratio,
        "damage_percent": round(damage, 6),
        "fatigue_cycles": cycles,
        "building_height_m": BUILDING_HEIGHT,
        "cross_section": f"{CROSS_SECTION_WIDTH}x{CROSS_SECTION_DEPTH} m",
    }


if __name__ == "__main__":
    import sys

    print("=" * 56)
    print(" stress_model self-test (no hardware needed)")
    print("=" * 56)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    material_db.set_active("reinforced_concrete")

    print("\n[1] Zero acceleration produces zero stress")
    state.update(ax=0.0, ay=0.0)
    _compute_cycle()
    _check(
        "bending_stress == 0",
        state.bending_stress == 0.0,
        f"(got {state.bending_stress})",
    )
    _check(
        "shear_stress == 0",
        state.shear_stress == 0.0,
        f"(got {state.shear_stress})",
    )
    _check(
        "stress_ratio == 0",
        state.stress_ratio == 0.0,
        f"(got {state.stress_ratio})",
    )

    print("\n[2] Non-zero acceleration produces positive stress")
    reset_damage()
    state.update(ax=0.1, ay=0.0)
    _compute_cycle()
    _check(
        "bending_stress > 0",
        state.bending_stress > 0,
        f"(got {state.bending_stress})",
    )
    _check(
        "shear_stress > 0",
        state.shear_stress > 0,
        f"(got {state.shear_stress})",
    )

    print("\n[3] Stress ratio is clamped to [0, 1]")
    reset_damage()
    state.update(ax=5.0, ay=5.0)
    _compute_cycle()
    _check(
        "stress_ratio <= 1.0",
        state.stress_ratio <= 1.0,
        f"(got {state.stress_ratio})",
    )

    print("\n[4] Fatigue damage accumulates")
    reset_damage()
    state.update(ax=0.5, ay=0.0)
    for _ in range(100):
        _compute_cycle()
    _check(
        "damage_percent > 0",
        state.damage_percent > 0,
        f"(got {state.damage_percent}%)",
    )
    _check(
        "fatigue_cycles == 100",
        state.fatigue_cycles == 100,
        f"(got {state.fatigue_cycles})",
    )

    print("\n[5] reset_damage() clears damage")
    reset_damage()
    _check(
        "damage_percent == 0 after reset",
        state.damage_percent == 0.0,
        f"(got {state.damage_percent})",
    )
    _check(
        "fatigue_cycles == 0 after reset",
        state.fatigue_cycles == 0,
        f"(got {state.fatigue_cycles})",
    )

    print("\n[6] get_damage_report() returns valid dict")
    state.update(ax=0.2, ay=0.1)
    _compute_cycle()
    report = get_damage_report()
    _check(
        "report has 'material' key",
        "material" in report,
        f"(keys={list(report.keys())})",
    )
    _check(
        "material is reinforced_concrete",
        report["material"] == "reinforced_concrete",
        f"(got {report['material']})",
    )

    print("\n[7] Bending stress formula verification")
    reset_damage()
    state.update(ax=0.1, ay=0.0)
    _compute_cycle()
    accel_ms2 = 0.1 * 9.81
    expected_force = MASS_ESTIMATE * accel_ms2
    expected_moment = expected_force * BUILDING_HEIGHT
    expected_sigma = (expected_moment * C / I) / 1e6
    _check(
        "bending matches hand calc",
        abs(state.bending_stress - round(expected_sigma, 4)) < 1e-3,
        f"(got {state.bending_stress}, expected {expected_sigma:.4f})",
    )

    print("\n" + "=" * 56)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
