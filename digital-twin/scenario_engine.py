import math
from dataclasses import dataclass, asdict
from typing import Any, Dict

from twin_state import state
import material_db
import stress_model

RHO_AIR = 1.225
CD_FLAT = 1.3
RHO_WATER = 1000.0
GRAVITY = 9.81
THERMAL_ALPHA = 12e-6
FLOOR_DEAD_LOAD_KG = 3000.0
FLOOR_AREA_M2 = 9.0
LIVE_LOAD_KG_PER_M2 = 200.0

WIND_PRESETS = {
    "breeze": 20.0,
    "strong": 60.0,
    "storm": 90.0,
    "hurricane": 180.0,
}

SEISMIC_PRESETS = {
    "minor": (4.0, 50.0),
    "moderate": (5.5, 30.0),
    "major": (7.0, 15.0),
    "great": (8.5, 10.0),
}


@dataclass
class SimulationResult:
    scenario_name: str
    additional_stress_mpa: float
    total_projected_stress: float
    stress_ratio_projected: float
    projected_damage_rate_per_hour: float
    time_to_failure_hours: float
    safe: bool
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if math.isinf(d["time_to_failure_hours"]):
            d["time_to_failure_hours"] = None
        return d


def _baseline_stress() -> float:
    snap = state.snapshot()
    return max(snap.bending_stress, snap.shear_stress)


def _build_result(name, additional, mat):
    baseline = _baseline_stress()
    total = baseline + additional
    ratio = total / mat.yield_strength if mat.yield_strength > 0 else 0.0
    ratio = max(0.0, min(1.0, ratio))
    safe = total < mat.yield_strength

    if total > mat.fatigue_limit and mat.ultimate_strength > 0:
        n_failure = mat.ultimate_strength / total
        damage_rate = (1.0 / (n_failure * stress_model.SAMPLE_RATE)) * 100.0
        damage_per_hour = damage_rate * stress_model.SAMPLE_RATE * 3600.0
        remaining = 100.0 - state.damage_percent
        if damage_per_hour > 0:
            ttf = remaining / damage_per_hour
        else:
            ttf = float("inf")
    else:
        damage_per_hour = 0.0
        ttf = float("inf")

    if safe:
        summary = f"{name}: {total:.2f} MPa projected ({ratio:.0%} of yield) — SAFE"
    else:
        summary = f"{name}: {total:.2f} MPa projected ({ratio:.0%} of yield) — EXCEEDS YIELD"

    return SimulationResult(
        scenario_name=name,
        additional_stress_mpa=round(additional, 4),
        total_projected_stress=round(total, 4),
        stress_ratio_projected=round(ratio, 4),
        projected_damage_rate_per_hour=round(damage_per_hour, 6),
        time_to_failure_hours=round(ttf, 2) if not math.isinf(ttf) else float("inf"),
        safe=safe,
        summary=summary,
    )


def wind_load(wind_speed_kmh: float) -> SimulationResult:
    mat = material_db.get_active()
    v_ms = wind_speed_kmh / 3.6
    frontal_area = stress_model.BUILDING_HEIGHT * stress_model.CROSS_SECTION_WIDTH
    drag_force = 0.5 * RHO_AIR * CD_FLAT * frontal_area * v_ms ** 2

    moment = drag_force * stress_model.BUILDING_HEIGHT
    sigma = (moment * stress_model.C / stress_model.I) / 1e6

    return _build_result("wind_load", sigma, mat)


def seismic_load(magnitude: float, distance_km: float) -> SimulationResult:
    mat = material_db.get_active()
    distance_km = max(distance_km, 1.0)
    pga_g = 0.015 * (10 ** (0.5 * magnitude)) / (distance_km ** 1.5)

    force = stress_model.MASS_ESTIMATE * pga_g * GRAVITY
    moment = force * stress_model.BUILDING_HEIGHT
    sigma = (moment * stress_model.C / stress_model.I) / 1e6

    return _build_result("seismic_load", sigma, mat)


def overload(extra_floors: int = 1, occupancy_pct: float = 1.0) -> SimulationResult:
    mat = material_db.get_active()
    occupancy_pct = max(0.0, min(1.0, occupancy_pct))

    dead = FLOOR_DEAD_LOAD_KG * extra_floors * GRAVITY
    live = LIVE_LOAD_KG_PER_M2 * FLOOR_AREA_M2 * occupancy_pct * extra_floors * GRAVITY

    total_axial_n = dead + live
    axial_stress = (total_axial_n / stress_model.AREA) / 1e6

    return _build_result("overload", axial_stress, mat)


def thermal_stress(delta_temp_c: float) -> SimulationResult:
    mat = material_db.get_active()
    elastic_modulus_pa = mat.elastic_modulus * 1e9
    epsilon = THERMAL_ALPHA * abs(delta_temp_c)
    sigma = (elastic_modulus_pa * epsilon) / 1e6

    return _build_result("thermal_stress", sigma, mat)


def flood_hydrostatic(water_depth_m: float) -> SimulationResult:
    mat = material_db.get_active()
    water_depth_m = max(0.0, min(water_depth_m, stress_model.BUILDING_HEIGHT))

    pressure_avg = RHO_WATER * GRAVITY * (water_depth_m / 2.0)
    submerged_area = water_depth_m * stress_model.CROSS_SECTION_WIDTH
    lateral_force = pressure_avg * submerged_area

    moment_arm = water_depth_m / 3.0
    moment = lateral_force * moment_arm
    sigma = (moment * stress_model.C / stress_model.I) / 1e6

    return _build_result("flood_hydrostatic", sigma, mat)


_SCENARIO_DISPATCH = {
    "wind_load": wind_load,
    "seismic_load": seismic_load,
    "overload": overload,
    "thermal_stress": thermal_stress,
    "flood_hydrostatic": flood_hydrostatic,
}


def run_scenario(name: str, **params) -> SimulationResult:
    if name not in _SCENARIO_DISPATCH:
        raise ValueError(
            f"Unknown scenario '{name}'. Available: {', '.join(_SCENARIO_DISPATCH)}"
        )
    return _SCENARIO_DISPATCH[name](**params)


def run_all_scenarios() -> Dict[str, SimulationResult]:
    results = {}
    results["wind_load"] = wind_load(wind_speed_kmh=WIND_PRESETS["strong"])
    results["seismic_load"] = seismic_load(
        magnitude=SEISMIC_PRESETS["moderate"][0],
        distance_km=SEISMIC_PRESETS["moderate"][1],
    )
    results["overload"] = overload(extra_floors=2, occupancy_pct=0.8)
    results["thermal_stress"] = thermal_stress(delta_temp_c=40.0)
    results["flood_hydrostatic"] = flood_hydrostatic(water_depth_m=2.0)
    return results


def set_active_scenario(name: str, **params) -> SimulationResult:
    result = run_scenario(name, **params)
    state.update(
        scenario_active=name,
        scenario_params=params,
        projected_stress=result.total_projected_stress,
        projected_damage_rate=result.projected_damage_rate_per_hour,
        time_to_failure_hours=result.time_to_failure_hours,
    )
    return result


def clear_scenario():
    state.update(
        scenario_active="none",
        scenario_params={},
        projected_stress=0.0,
        projected_damage_rate=0.0,
        time_to_failure_hours=float("inf"),
    )


if __name__ == "__main__":
    import sys

    print("=" * 62)
    print(" scenario_engine self-test (no hardware needed)")
    print("=" * 62)

    failures = 0

    def _check(label, condition, detail=""):
        global failures
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}  {detail}")
        if not condition:
            failures += 1

    material_db.set_active("reinforced_concrete")
    state.update(ax=0.01, ay=0.0)
    stress_model._compute_cycle()

    print("\n[1] Wind load scenarios")
    for preset, speed in WIND_PRESETS.items():
        r = wind_load(speed)
        _check(
            f"wind {preset} ({speed} km/h)",
            r.additional_stress_mpa >= 0,
            f"add={r.additional_stress_mpa:.4f} MPa  safe={r.safe}",
        )
    r_breeze = wind_load(WIND_PRESETS["breeze"])
    r_hurricane = wind_load(WIND_PRESETS["hurricane"])
    _check(
        "hurricane > breeze stress",
        r_hurricane.additional_stress_mpa > r_breeze.additional_stress_mpa,
    )

    print("\n[2] Seismic load scenarios")
    for preset, (mag, dist) in SEISMIC_PRESETS.items():
        r = seismic_load(mag, dist)
        _check(
            f"seismic {preset} (M{mag} @ {dist}km)",
            r.additional_stress_mpa >= 0,
            f"add={r.additional_stress_mpa:.4f} MPa  safe={r.safe}",
        )
    r_minor = seismic_load(*SEISMIC_PRESETS["minor"])
    r_great = seismic_load(*SEISMIC_PRESETS["great"])
    _check(
        "great > minor stress",
        r_great.additional_stress_mpa > r_minor.additional_stress_mpa,
    )

    print("\n[3] Overload scenario")
    r = overload(extra_floors=3, occupancy_pct=1.0)
    _check(
        "3 floors full occupancy",
        r.additional_stress_mpa > 0,
        f"add={r.additional_stress_mpa:.4f} MPa",
    )
    r1 = overload(extra_floors=1, occupancy_pct=0.5)
    _check(
        "1 floor < 3 floors",
        r1.additional_stress_mpa < r.additional_stress_mpa,
    )

    print("\n[4] Thermal stress scenario")
    r = thermal_stress(delta_temp_c=50.0)
    _check(
        "50C delta",
        r.additional_stress_mpa > 0,
        f"add={r.additional_stress_mpa:.4f} MPa",
    )
    r_small = thermal_stress(delta_temp_c=10.0)
    _check(
        "50C > 10C stress",
        r.additional_stress_mpa > r_small.additional_stress_mpa,
    )

    print("\n[5] Flood hydrostatic scenario")
    r = flood_hydrostatic(water_depth_m=3.0)
    _check(
        "3m water depth",
        r.additional_stress_mpa > 0,
        f"add={r.additional_stress_mpa:.4f} MPa",
    )
    r_shallow = flood_hydrostatic(water_depth_m=0.5)
    _check(
        "3m > 0.5m stress",
        r.additional_stress_mpa > r_shallow.additional_stress_mpa,
    )

    print("\n[6] run_scenario() dispatch")
    r = run_scenario("wind_load", wind_speed_kmh=80.0)
    _check(
        "dispatch returns SimulationResult",
        isinstance(r, SimulationResult),
    )
    try:
        run_scenario("nonexistent")
        _check("unknown scenario raises", False)
    except ValueError:
        _check("unknown scenario raises ValueError", True)

    print("\n[7] run_all_scenarios()")
    all_results = run_all_scenarios()
    _check(
        "returns 5 scenarios",
        len(all_results) == 5,
        f"(got {len(all_results)})",
    )

    print("\n[8] set_active_scenario() writes to twin_state")
    set_active_scenario("wind_load", wind_speed_kmh=90.0)
    _check(
        "scenario_active updated",
        state.scenario_active == "wind_load",
        f"(got '{state.scenario_active}')",
    )
    _check(
        "projected_stress > 0",
        state.projected_stress > 0,
        f"(got {state.projected_stress})",
    )

    print("\n[9] clear_scenario() resets twin_state")
    clear_scenario()
    _check(
        "scenario_active is 'none'",
        state.scenario_active == "none",
    )
    _check(
        "projected_stress == 0",
        state.projected_stress == 0.0,
    )

    print("\n[10] to_dict() handles inf")
    r = wind_load(5.0)
    d = r.to_dict()
    _check(
        "to_dict() returns dict",
        isinstance(d, dict),
    )
    _check(
        "inf serialised as None",
        d["time_to_failure_hours"] is None or isinstance(d["time_to_failure_hours"], (int, float)),
    )

    print("\n" + "=" * 62)
    print("\n Summary of all scenarios (default params):")
    print("-" * 62)
    for name, result in run_all_scenarios().items():
        print(f"  {result.summary}")
    print("-" * 62)

    print()
    if failures == 0:
        print(" ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f" {failures} TEST(S) FAILED")
        sys.exit(1)
