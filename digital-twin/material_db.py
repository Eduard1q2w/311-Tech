from dataclasses import dataclass
from typing import Dict, List

from twin_state import state


@dataclass(frozen=True)
class MaterialProfile:
    name: str
    yield_strength: float
    ultimate_strength: float
    elastic_modulus: float
    shear_modulus: float
    fatigue_limit: float
    density: float
    damping_ratio: float
    max_drift_ratio: float
    description: str


MATERIALS: Dict[str, MaterialProfile] = {
    "reinforced_concrete": MaterialProfile(
        name="reinforced_concrete",
        yield_strength=30.0,
        ultimate_strength=40.0,
        elastic_modulus=30.0,
        shear_modulus=12.5,
        fatigue_limit=12.0,
        density=2400.0,
        damping_ratio=0.05,
        max_drift_ratio=0.02,
        description="Standard reinforced concrete (C30/37 grade)",
    ),
    "structural_steel": MaterialProfile(
        name="structural_steel",
        yield_strength=275.0,
        ultimate_strength=430.0,
        elastic_modulus=210.0,
        shear_modulus=81.0,
        fatigue_limit=110.0,
        density=7850.0,
        damping_ratio=0.02,
        max_drift_ratio=0.025,
        description="Structural steel S275 grade per EN 10025",
    ),
    "glulam_timber": MaterialProfile(
        name="glulam_timber",
        yield_strength=24.0,
        ultimate_strength=30.0,
        elastic_modulus=12.6,
        shear_modulus=0.72,
        fatigue_limit=9.6,
        density=450.0,
        damping_ratio=0.08,
        max_drift_ratio=0.015,
        description="Glued-laminated timber GL24h per EN 14080",
    ),
    "unreinforced_masonry": MaterialProfile(
        name="unreinforced_masonry",
        yield_strength=3.5,
        ultimate_strength=5.0,
        elastic_modulus=7.0,
        shear_modulus=2.8,
        fatigue_limit=1.4,
        density=1800.0,
        damping_ratio=0.07,
        max_drift_ratio=0.005,
        description="Unreinforced clay-brick masonry (EN 1996)",
    ),
    "prestressed_concrete": MaterialProfile(
        name="prestressed_concrete",
        yield_strength=45.0,
        ultimate_strength=60.0,
        elastic_modulus=36.0,
        shear_modulus=15.0,
        fatigue_limit=18.0,
        density=2500.0,
        damping_ratio=0.04,
        max_drift_ratio=0.015,
        description="Post-tensioned prestressed concrete (C50/60)",
    ),
    "aluminium_alloy": MaterialProfile(
        name="aluminium_alloy",
        yield_strength=276.0,
        ultimate_strength=310.0,
        elastic_modulus=68.9,
        shear_modulus=26.0,
        fatigue_limit=96.5,
        density=2700.0,
        damping_ratio=0.03,
        max_drift_ratio=0.02,
        description="Aluminium 6061-T6 per ASTM B308",
    ),
}


def get_material(name: str) -> MaterialProfile:
    if name not in MATERIALS:
        raise ValueError(
            f"Unknown material '{name}'. Available: {', '.join(MATERIALS)}"
        )
    return MATERIALS[name]


def list_materials() -> List[str]:
    return list(MATERIALS.keys())


def set_active(name: str) -> None:
    mat = get_material(name)
    state.update(
        active_material=mat.name,
        yield_strength=mat.yield_strength,
        elastic_modulus=mat.elastic_modulus,
        fatigue_limit=mat.fatigue_limit,
        damping_ratio=mat.damping_ratio,
    )


def get_active() -> MaterialProfile:
    return get_material(state.active_material)


if __name__ == "__main__":
    header = (
        f"{'Name':<25} {'Yield':>8} {'Ult':>8} {'E':>8} {'G':>8} "
        f"{'Fatigue':>8} {'Density':>8} {'Damp':>6} {'Drift':>6}"
    )
    units = (
        f"{'':25} {'MPa':>8} {'MPa':>8} {'GPa':>8} {'GPa':>8} "
        f"{'MPa':>8} {'kg/m3':>8} {'':>6} {'':>6}"
    )

    print("=" * len(header))
    print(" Structural Material Database")
    print("=" * len(header))
    print(header)
    print(units)
    print("-" * len(header))

    for mat in MATERIALS.values():
        print(
            f"{mat.name:<25} {mat.yield_strength:>8.1f} {mat.ultimate_strength:>8.1f} "
            f"{mat.elastic_modulus:>8.1f} {mat.shear_modulus:>8.1f} "
            f"{mat.fatigue_limit:>8.1f} {mat.density:>8.0f} "
            f"{mat.damping_ratio:>6.3f} {mat.max_drift_ratio:>6.3f}"
        )

    print("-" * len(header))
    print(f" {len(MATERIALS)} materials loaded")

    print("\n[set_active] Setting 'structural_steel' as active material...")
    set_active("structural_steel")
    active = get_active()
    print(f"  active_material  = {state.active_material}")
    print(f"  yield_strength   = {state.yield_strength} MPa")
    print(f"  elastic_modulus  = {state.elastic_modulus} GPa")
    print(f"  fatigue_limit    = {state.fatigue_limit} MPa")
    print(f"  damping_ratio    = {state.damping_ratio}")
    print("  OK")
