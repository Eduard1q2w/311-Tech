import math
from dataclasses import dataclass, field, fields, asdict
from threading import RLock
from typing import Any, Dict, List


@dataclass
class TwinState:
    ax: float = 0.0
    ay: float = 0.0
    az: float = 0.0
    tilt_x: float = 0.0
    tilt_y: float = 0.0
    timestamp: float = 0.0

    sway_velocity_x: float = 0.0
    sway_velocity_y: float = 0.0
    lateral_displacement: float = 0.0
    torsion_angle: float = 0.0
    dominant_frequency: float = 0.0

    active_material: str = "reinforced_concrete"
    yield_strength: float = 0.0
    elastic_modulus: float = 0.0
    fatigue_limit: float = 0.0
    damping_ratio: float = 0.0

    bending_stress: float = 0.0
    shear_stress: float = 0.0
    stress_ratio: float = 0.0
    damage_percent: float = 0.0
    fatigue_cycles: int = 0

    scenario_active: str = "none"
    scenario_params: Dict[str, Any] = field(default_factory=dict)
    projected_stress: float = 0.0
    projected_damage_rate: float = 0.0
    time_to_failure_hours: float = float("inf")

    integrity_score: float = 100.0
    alert_tier: str = "nominal"
    forecast_24h: List[float] = field(default_factory=lambda: [100.0] * 24)
    evacuation_flag: bool = False
    resonance_warning: bool = False

    def __post_init__(self):
        self._lock = RLock()
        self._field_names = {f.name for f in fields(self)}

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if key in self._field_names:
                    setattr(self, key, value)

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            snapshot = asdict(self)
        return _sanitize_for_json(snapshot)

    def snapshot(self) -> "TwinState":
        with self._lock:
            values = {name: getattr(self, name) for name in self._field_names}
        copy = TwinState(**{k: v for k, v in values.items() if not isinstance(v, (dict, list))})
        for k, v in values.items():
            if isinstance(v, dict):
                setattr(copy, k, dict(v))
            elif isinstance(v, list):
                setattr(copy, k, list(v))
        return copy


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, float):
        if math.isinf(value) or math.isnan(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_for_json(v) for v in value]
    return value


state = TwinState()
