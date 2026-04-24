import threading
import time

from twin_state import state
import material_db
import scenario_engine
import stress_model
import predictor


STREAM_DURATION_S = 10.0
STREAM_INTERVAL_S = 0.1
SCENARIO_MAP = {
    "wind": "wind_load",
    "seismic": "seismic_load",
    "overload": "overload",
    "thermal": "thermal_stress",
    "flood": "flood_hydrostatic",
}

_lock = threading.Lock()
_cancel_event = threading.Event()
_active_thread = None
_active_name = None


def _params_from_intensity(kind, intensity):
    intensity = max(0.0, min(1.0, float(intensity)))
    if kind == "wind":
        return {"wind_speed_kmh": 20.0 + intensity * 180.0}
    if kind == "seismic":
        return {
            "magnitude": 4.0 + intensity * 4.5,
            "distance_km": max(1.0, 50.0 - intensity * 40.0),
        }
    if kind == "overload":
        return {
            "extra_floors": int(round(1 + intensity * 4)),
            "occupancy_pct": max(0.1, intensity),
        }
    if kind == "thermal":
        return {"delta_temp_c": intensity * 60.0}
    if kind == "flood":
        return {"water_depth_m": intensity * 5.0}
    return {}


def _compute_integrity(stress_ratio, damage_pct, torsion, dom_freq):
    score = 100.0
    if stress_ratio > 0.3:
        score -= (stress_ratio - 0.3) * 60.0
    score -= damage_pct
    if abs(torsion) > 2.0:
        score -= abs(torsion) * 2.0
    if dom_freq > 0 and 0.8 < dom_freq < 1.2:
        score -= 10.0
    return max(0.0, min(100.0, score))


def _tier(score):
    if score >= 80: return "nominal"
    if score >= 60: return "watch"
    if score >= 40: return "warning"
    if score >= 20: return "critical"
    return "evacuate"


def _emit(socketio, payload):
    socketio.emit("scenario_stream", payload)


def _run(socketio, kind, scenario_name, params):
    global _active_name
    try:
        result = scenario_engine.run_scenario(scenario_name, **params)
    except Exception as e:
        _emit(socketio, {
            "phase": "error",
            "scenario": kind,
            "message": f"{type(e).__name__}: {e}",
        })
        with _lock:
            _active_name = None
        return

    snap0 = state.snapshot()
    baseline_bending = snap0.bending_stress
    baseline_shear = snap0.shear_stress
    baseline_disp = snap0.lateral_displacement
    baseline_damage = snap0.damage_percent
    baseline_torsion = snap0.torsion_angle
    baseline_dom_freq = snap0.dominant_frequency

    target_stress = result.total_projected_stress
    mat = material_db.get_active()
    yield_s = mat.yield_strength if mat.yield_strength > 0 else 1.0
    target_disp_mm = baseline_disp + 50.0 * (
        1.0 if kind in ("wind", "seismic") else 0.4
    ) * (target_stress / yield_s)
    target_damage_addl = result.projected_damage_rate_per_hour * (STREAM_DURATION_S / 3600.0)

    n_steps = int(STREAM_DURATION_S / STREAM_INTERVAL_S)
    _emit(socketio, {
        "phase": "start",
        "scenario": kind,
        "scenario_full": scenario_name,
        "duration_s": STREAM_DURATION_S,
        "n_steps": n_steps,
        "target_stress_mpa": target_stress,
        "target_ttf_hours": None if result.time_to_failure_hours == float("inf")
            else result.time_to_failure_hours,
        "summary": result.summary,
        "safe": result.safe,
    })

    t0 = time.time()
    for i in range(n_steps + 1):
        if _cancel_event.is_set():
            break
        t = i / n_steps
        ease = t * t * (3 - 2 * t)
        bending = baseline_bending + (target_stress - baseline_bending) * ease
        shear = baseline_shear + (target_stress * 0.25 - baseline_shear) * ease
        peak = max(bending, shear)
        ratio = max(0.0, min(1.0, peak / yield_s))
        disp = baseline_disp + (target_disp_mm - baseline_disp) * ease
        damage = baseline_damage + target_damage_addl * t
        integrity = _compute_integrity(ratio, damage, baseline_torsion, baseline_dom_freq)
        tier = _tier(integrity)

        _emit(socketio, {
            "phase": "frame",
            "scenario": kind,
            "step": i,
            "n_steps": n_steps,
            "t_s": round(time.time() - t0, 3),
            "progress": round(t, 4),
            "bending_stress": round(bending, 3),
            "shear_stress": round(shear, 3),
            "stress_ratio": round(ratio, 4),
            "lateral_displacement": round(disp, 2),
            "damage_percent": round(damage, 4),
            "integrity_score": round(integrity, 1),
            "alert_tier": tier,
        })
        time.sleep(STREAM_INTERVAL_S)

    aborted = _cancel_event.is_set()
    _emit(socketio, {
        "phase": "end",
        "scenario": kind,
        "aborted": aborted,
    })

    with _lock:
        _active_name = None


def start_scenario(socketio, kind, intensity):
    global _active_thread, _active_name
    if kind not in SCENARIO_MAP:
        raise ValueError(f"Unknown scenario '{kind}'. Known: {list(SCENARIO_MAP)}")
    scenario_name = SCENARIO_MAP[kind]
    params = _params_from_intensity(kind, intensity)

    with _lock:
        if _active_thread is not None and _active_thread.is_alive():
            _cancel_event.set()
            _active_thread.join(timeout=1.0)
        _cancel_event.clear()
        _active_name = kind
        _active_thread = threading.Thread(
            target=_run, args=(socketio, kind, scenario_name, params),
            name=f"ScenarioStream:{kind}", daemon=True,
        )
        _active_thread.start()

    return {
        "status": "ok",
        "scenario": kind,
        "scenario_full": scenario_name,
        "intensity": intensity,
        "params": params,
    }


def stop_scenario():
    with _lock:
        kind = _active_name
        was_active = _active_thread is not None and _active_thread.is_alive()
    if was_active:
        _cancel_event.set()
    return {"status": "ok", "aborted": was_active, "scenario": kind}


def is_active():
    with _lock:
        return _active_thread is not None and _active_thread.is_alive()


def current_scenario():
    with _lock:
        return _active_name
