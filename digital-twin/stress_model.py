import math
import threading

from twin_state import state
import material_db

SAMPLE_RATE = 20.0
CYCLE_INTERVAL = 1.0 / SAMPLE_RATE
GRAVITY = 9.81

BUILDING_HEIGHT = 9.9
CROSS_SECTION_WIDTH = 10.0
CROSS_SECTION_DEPTH = 10.0
MASS_ESTIMATE = 1_039_500.0

I = (CROSS_SECTION_WIDTH * CROSS_SECTION_DEPTH ** 3) / 12.0
C = CROSS_SECTION_DEPTH / 2.0
AREA = CROSS_SECTION_WIDTH * CROSS_SECTION_DEPTH

_stop_event = threading.Event()
_thread = None
_damage_lock = threading.Lock()
_cumulative_damage = 0.0
_total_cycles = 0


def _recompute_section_props():
    global I, C, AREA
    I = (CROSS_SECTION_WIDTH * CROSS_SECTION_DEPTH ** 3) / 12.0
    C = CROSS_SECTION_DEPTH / 2.0
    AREA = CROSS_SECTION_WIDTH * CROSS_SECTION_DEPTH


def set_dimensions(height_m: float, width_m: float, depth_m: float, mass_kg: float,
                   stories: int = None, floor_height: float = None,
                   plan_width: float = None, plan_depth: float = None,
                   structural_system: str = None):
    global BUILDING_HEIGHT, CROSS_SECTION_WIDTH, CROSS_SECTION_DEPTH, MASS_ESTIMATE
    with _damage_lock:
        BUILDING_HEIGHT = max(0.01, float(height_m))
        CROSS_SECTION_WIDTH = max(0.01, float(width_m))
        CROSS_SECTION_DEPTH = max(0.01, float(depth_m))
        MASS_ESTIMATE = max(0.01, float(mass_kg))
        _recompute_section_props()

        update_fields = {
            "building_height_m": BUILDING_HEIGHT,
            "cross_section_width_m": CROSS_SECTION_WIDTH,
            "cross_section_depth_m": CROSS_SECTION_DEPTH,
            "mass_estimate_kg": MASS_ESTIMATE,
        }
        if stories is not None:
            update_fields["stories"] = int(stories)
        if floor_height is not None:
            update_fields["floor_height"] = float(floor_height)
        if plan_width is not None:
            update_fields["plan_width"] = float(plan_width)
        if plan_depth is not None:
            update_fields["plan_depth"] = float(plan_depth)
        if structural_system is not None:
            update_fields["structural_system"] = str(structural_system)
        state.update(**update_fields)


def _governing_strength(mat):
    candidates = [
        getattr(mat, "yield_strength_mpa", 0.0),
        getattr(mat, "compressive_strength_mpa", 0.0),
        getattr(mat, "yield_strength", 0.0),
    ]
    values = [v for v in candidates if v and v > 0.0]
    return max(values) if values else 1.0


def _compute_cycle():
    global _cumulative_damage, _total_cycles

    snap = state.snapshot()
    mat = material_db.get_active()

    stories = max(1, int(snap.stories) if snap.stories else 1)
    floor_h = float(snap.floor_height) if snap.floor_height > 0 else 3.3
    H = max(0.01, stories * floor_h)
    b = max(0.01, float(snap.plan_width) if snap.plan_width > 0 else CROSS_SECTION_WIDTH)
    d = max(0.01, float(snap.plan_depth) if snap.plan_depth > 0 else CROSS_SECTION_DEPTH)
    mass_total = max(0.01, float(snap.mass_estimate_kg) if snap.mass_estimate_kg > 0 else MASS_ESTIMATE)

    I_local = (b * d ** 3) / 12.0
    c_local = d / 2.0
    area_local = b * d

    acc_x = float(snap.ax)
    acc_y = float(snap.ay)
    acc_peak_g = max(abs(acc_x), abs(acc_y))

    V = mass_total * acc_peak_g * GRAVITY
    M_moment = V * H

    sigma_bending_pa = (M_moment * c_local) / I_local if I_local > 0 else 0.0
    sigma_bending = sigma_bending_pa / 1e6

    Q = (b * (d / 2.0) ** 2) / 2.0
    tau_shear_pa = (V * Q) / (I_local * b) if (I_local * b) > 0 else 0.0
    tau_shear = tau_shear_pa / 1e6

    peak_stress = max(sigma_bending, tau_shear)
    limit_mpa = _governing_strength(mat)
    ratio = peak_stress / limit_mpa if limit_mpa > 0 else 0.0
    ratio = max(0.0, min(1.0, ratio))

    sn_slope = getattr(mat, "sn_slope", 0.0)
    sn_ref_cycles = getattr(mat, "sn_reference_cycles", 0.0)
    sn_ref_stress = getattr(mat, "sn_reference_stress_mpa", 0.0)
    fatigue_limit_mpa = max(0.0, float(mat.fatigue_limit))

    dom_freq = float(snap.dominant_frequency) if snap.dominant_frequency > 0 else 1.0
    n_cycles_interval = dom_freq * CYCLE_INTERVAL

    with _damage_lock:
        if (peak_stress > fatigue_limit_mpa
                and sn_slope > 0.0
                and sn_ref_cycles > 0.0
                and sn_ref_stress > 0.0):
            N_i = sn_ref_cycles * (sn_ref_stress / peak_stress) ** sn_slope
            if N_i > 0:
                delta_D = n_cycles_interval / N_i
                _cumulative_damage = min(1.0, _cumulative_damage + delta_D)
        _total_cycles += 1
        damage_frac = _cumulative_damage
        cycles = _total_cycles

    damage_pct = damage_frac * 100.0

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


def get_cumulative_damage_fraction():
    with _damage_lock:
        return _cumulative_damage


def get_damage_report():
    snap = state.snapshot()
    mat = material_db.get_active()
    with _damage_lock:
        damage_frac = _cumulative_damage
        cycles = _total_cycles
    return {
        "material": mat.name,
        "yield_strength_mpa": mat.yield_strength,
        "ultimate_strength_mpa": mat.ultimate_strength,
        "fatigue_limit_mpa": mat.fatigue_limit,
        "governing_strength_mpa": _governing_strength(mat),
        "sn_slope": getattr(mat, "sn_slope", None),
        "sn_reference_cycles": getattr(mat, "sn_reference_cycles", None),
        "sn_reference_stress_mpa": getattr(mat, "sn_reference_stress_mpa", None),
        "bending_stress_mpa": snap.bending_stress,
        "shear_stress_mpa": snap.shear_stress,
        "stress_ratio": snap.stress_ratio,
        "damage_fraction": round(damage_frac, 9),
        "damage_percent": round(damage_frac * 100.0, 6),
        "fatigue_cycles": cycles,
        "building_height_m": snap.building_height_m,
        "cross_section": f"{snap.plan_width}x{snap.plan_depth} m",
    }


if __name__ == "__main__":
    import sys

    print("=" * 56)
    print(" Durian stress_model self-test")
    print("=" * 56)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    material_db.set_active("reinforced_concrete")
    state.update(stories=3, floor_height=3.3, plan_width=10.0, plan_depth=10.0,
                 mass_estimate_kg=500000.0)

    print("\n[1] Zero acceleration produces zero stress")
    state.update(ax=0.0, ay=0.0)
    _compute_cycle()
    _check("bending == 0", state.bending_stress == 0.0, f"(got {state.bending_stress})")
    _check("shear == 0", state.shear_stress == 0.0, f"(got {state.shear_stress})")
    _check("ratio == 0", state.stress_ratio == 0.0, f"(got {state.stress_ratio})")

    print("\n[2] Non-zero acceleration produces positive stress")
    reset_damage()
    state.update(ax=0.05, ay=0.0)
    _compute_cycle()
    _check("bending > 0", state.bending_stress > 0, f"(got {state.bending_stress})")
    _check("shear > 0", state.shear_stress > 0, f"(got {state.shear_stress})")

    print("\n[3] Stress ratio clamped to [0, 1]")
    reset_damage()
    state.update(ax=5.0, ay=5.0)
    _compute_cycle()
    _check("ratio <= 1.0", state.stress_ratio <= 1.0, f"(got {state.stress_ratio})")

    print("\n[4] Fatigue damage accumulates at high stress using S-N curve")
    reset_damage()
    state.update(ax=0.5, ay=0.0, dominant_frequency=2.0)
    for _ in range(200):
        _compute_cycle()
    _check("damage_percent > 0", state.damage_percent > 0, f"(got {state.damage_percent}%)")
    _check("fatigue_cycles == 200", state.fatigue_cycles == 200, f"(got {state.fatigue_cycles})")

    print("\n[5] reset_damage()")
    reset_damage()
    _check("damage == 0", state.damage_percent == 0.0)
    _check("cycles == 0", state.fatigue_cycles == 0)

    print("\n[6] get_damage_report() has S-N fields")
    state.update(ax=0.2, ay=0.1)
    _compute_cycle()
    report = get_damage_report()
    _check("has sn_slope", report.get("sn_slope") is not None)
    _check("has sn_reference_cycles", report.get("sn_reference_cycles") is not None)
    _check("has sn_reference_stress_mpa", report.get("sn_reference_stress_mpa") is not None)

    print("\n[7] Bending = M*c/I matches hand calc")
    reset_damage()
    state.update(ax=0.1, ay=0.0, stories=3, floor_height=3.3,
                 plan_width=10.0, plan_depth=10.0, mass_estimate_kg=500000.0)
    _compute_cycle()
    H = 3 * 3.3
    b_ = 10.0
    d_ = 10.0
    I_ = (b_ * d_ ** 3) / 12.0
    c_ = d_ / 2.0
    V_exp = 500000.0 * 0.1 * GRAVITY
    M_exp = V_exp * H
    sigma_exp = (M_exp * c_ / I_) / 1e6
    _check("bending matches hand calc",
           abs(state.bending_stress - round(sigma_exp, 4)) < 1e-2,
           f"(got {state.bending_stress}, expected {sigma_exp:.4f})")

    print("\n" + "=" * 56)
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
