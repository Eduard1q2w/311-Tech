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
    yield_strength_mpa: float
    compressive_strength_mpa: float
    sn_slope: float
    sn_reference_cycles: float
    sn_reference_stress_mpa: float
    stress_weight: float
    fatigue_weight: float
    disp_weight: float


MATERIALS: Dict[str, MaterialProfile] = {
    "reinforced_concrete": MaterialProfile(
        name="reinforced_concrete",
        yield_strength=30.0,
        ultimate_strength=40.0,
        elastic_modulus=33.0,
        shear_modulus=13.75,
        fatigue_limit=12.0,
        density=2500.0,
        damping_ratio=0.05,
        max_drift_ratio=0.02,
        description="Reinforced concrete C30/37 per EN 1992-1-1",
        yield_strength_mpa=30.0,
        compressive_strength_mpa=30.0,
        sn_slope=10.0,
        sn_reference_cycles=1.0e6,
        sn_reference_stress_mpa=9.0,
        stress_weight=0.35,
        fatigue_weight=0.20,
        disp_weight=0.10,
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
        description="Structural steel S275 per EN 1993-1-1 / EN 1993-1-9",
        yield_strength_mpa=275.0,
        compressive_strength_mpa=275.0,
        sn_slope=3.0,
        sn_reference_cycles=2.0e6,
        sn_reference_stress_mpa=80.0,
        stress_weight=0.25,
        fatigue_weight=0.35,
        disp_weight=0.10,
    ),
    "glulam_timber": MaterialProfile(
        name="glulam_timber",
        yield_strength=24.0,
        ultimate_strength=30.0,
        elastic_modulus=11.5,
        shear_modulus=0.65,
        fatigue_limit=9.6,
        density=420.0,
        damping_ratio=0.08,
        max_drift_ratio=0.015,
        description="Glulam GL24h per EN 1995-1-1 / EN 14080",
        yield_strength_mpa=24.0,
        compressive_strength_mpa=24.0,
        sn_slope=8.0,
        sn_reference_cycles=1.0e6,
        sn_reference_stress_mpa=7.0,
        stress_weight=0.25,
        fatigue_weight=0.15,
        disp_weight=0.25,
    ),
    "unreinforced_masonry": MaterialProfile(
        name="unreinforced_masonry",
        yield_strength=3.5,
        ultimate_strength=5.0,
        elastic_modulus=5.5,
        shear_modulus=2.2,
        fatigue_limit=1.4,
        density=1800.0,
        damping_ratio=0.07,
        max_drift_ratio=0.005,
        description="Unreinforced clay-brick masonry per EN 1996-1-1",
        yield_strength_mpa=3.5,
        compressive_strength_mpa=5.0,
        sn_slope=12.0,
        sn_reference_cycles=1.0e6,
        sn_reference_stress_mpa=1.2,
        stress_weight=0.40,
        fatigue_weight=0.10,
        disp_weight=0.25,
    ),
    "prestressed_concrete": MaterialProfile(
        name="prestressed_concrete",
        yield_strength=50.0,
        ultimate_strength=60.0,
        elastic_modulus=37.0,
        shear_modulus=15.4,
        fatigue_limit=20.0,
        density=2500.0,
        damping_ratio=0.04,
        max_drift_ratio=0.015,
        description="Post-tensioned prestressed concrete C50/60 per EN 1992-1-1",
        yield_strength_mpa=50.0,
        compressive_strength_mpa=50.0,
        sn_slope=10.0,
        sn_reference_cycles=1.0e6,
        sn_reference_stress_mpa=15.0,
        stress_weight=0.30,
        fatigue_weight=0.25,
        disp_weight=0.10,
    ),
    "aluminium_alloy": MaterialProfile(
        name="aluminium_alloy",
        yield_strength=240.0,
        ultimate_strength=290.0,
        elastic_modulus=70.0,
        shear_modulus=26.0,
        fatigue_limit=96.5,
        density=2700.0,
        damping_ratio=0.03,
        max_drift_ratio=0.02,
        description="Aluminium 6082-T6 per EN 1999-1-1",
        yield_strength_mpa=240.0,
        compressive_strength_mpa=240.0,
        sn_slope=4.0,
        sn_reference_cycles=5.0e6,
        sn_reference_stress_mpa=70.0,
        stress_weight=0.25,
        fatigue_weight=0.35,
        disp_weight=0.10,
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
        w_stress=mat.stress_weight,
        w_fatigue=mat.fatigue_weight,
        w_disp=mat.disp_weight,
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
    print(" Durian Structural Material Database")
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

    set_active("structural_steel")
    active = get_active()
    print(f"  active_material  = {state.active_material}")
    print(f"  yield_strength   = {state.yield_strength} MPa")
    print(f"  elastic_modulus  = {state.elastic_modulus} GPa")
    print(f"  fatigue_limit    = {state.fatigue_limit} MPa")
    print(f"  damping_ratio    = {state.damping_ratio}")
    print(f"  sn_slope         = {active.sn_slope}")
    print(f"  sn_ref_cycles    = {active.sn_reference_cycles:.1e}")
    print(f"  sn_ref_stress    = {active.sn_reference_stress_mpa} MPa")
    print(f"  weights (s/f/d)  = {active.stress_weight:.2f} / {active.fatigue_weight:.2f} / {active.disp_weight:.2f}")
    print("  OK")
