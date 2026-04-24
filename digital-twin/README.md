# Durian — Predictive Structural Digital Twin

Durian is a real-time structural-health digital twin that reads a low-cost MPU6050
accelerometer over I²C, processes the signal through a layered engineering stack
(signal conditioning → mechanics → stress → fatigue → prognosis), and serves a live
dashboard over Flask + Socket.IO. It is designed for a physical tabletop model of a
building and provides a faithful engineering computation chain, not a toy simulation.

All math is anchored in published civil-engineering formulas and in European design
standards (EN 1992 / 1993 / 1995 / 1996 / 1999). Every limit, weight and fatigue
parameter in the codebase has a corresponding real-world reference.

---

## 1. System architecture

```
  MPU6050 (I2C 0x68)
         │
         ▼
 [ sensor_reader ]──► raw x/y/z g at 20 Hz
         │
         ▼
 [ sensor_processor ]──► gravity-compensated, LPF-filtered
         │                tilt_x, tilt_y, tilt_magnitude
         │                deadbanded ax/ay/az
         ▼
 [ mechanics_engine ]──► sway velocity, lateral displacement,
         │                torsion angle, dominant frequency (FFT),
         │                baseline_frequency_hz, freq_shift_pct
         ▼
 [ stress_model ]──► bending σ = M·c/I, shear τ = V·Q/(I·b),
         │                stress ratio, Miner fatigue damage
         ▼
 [ predictor ]──► weighted integrity score, alert tier,
         │                exponential TTF, 24-hour forecast
         ▼
 [ server.py ]──Flask + Socket.IO──► browser dashboard

 [ scenario_engine ] + [ scenario_stream ] — on-demand what-if simulations
```

Every layer writes into the single shared `twin_state` (thread-safe dataclass with
an `RLock`), and the Flask process broadcasts the full snapshot at 20 Hz.

---

## 2. Repository layout

```
digital-twin/
├── server.py              Flask + Socket.IO entry point, boots all layers
├── twin_state.py          Thread-safe shared state (dataclass + RLock)
├── sensor_reader.py       MPU6050 I2C polling thread
├── sensor_processor.py    Calibration + Butterworth LPF + 3-axis tilt
├── mechanics_engine.py    HP drift compensation, double integration, FFT
├── stress_model.py        Bending + shear + Miner's rule fatigue
├── material_db.py         6 EN-standard material profiles
├── scenario_engine.py     Deterministic what-if calculations
├── scenario_stream.py     Timed 10-second streaming scenario runner
├── predictor.py           Composite integrity + TTF + forecast
├── templates/
│   └── index.html         Dashboard markup
├── static/
│   ├── app.js             Client logic (Socket.IO, Three.js, Chart.js)
│   └── style.css          Dashboard styling
└── ../3ddio/              OBJ/MTL assets for 3D building mesh
```

---

## 3. Hardware requirements

| Component | Role | Notes |
|---|---|---|
| Raspberry Pi (any model with I²C) | Host for the backend | `/dev/i2c-1` must be enabled via `raspi-config` |
| MPU6050 breakout | 3-axis accelerometer + gyro | Wired to I²C bus 1, default address `0x68` (`ACCEL_XOUT_H` at `0x3B`) |
| 5V / 2A power supply | Clean power for the Pi | Sensor powered from Pi 3.3 V rail |
| Ethernet / Wi-Fi LAN | Dashboard access | Server binds `0.0.0.0:5000`; local IP is printed on boot |

A desktop Linux or macOS host also works; the sensor layer will fail gracefully
(all downstream modules still run on synthetic state for UI / scenario work).

---

## 4. Python dependencies and their use case

| Package | Where it is used | Purpose in Durian |
|---|---|---|
| `flask` | `server.py` | HTTP server, routing, JSON response helpers |
| `flask-socketio` | `server.py` | WebSocket transport for 20 Hz state broadcasts + scenario frames |
| `eventlet` | `server.py` (monkey-patched first line) | Green-thread async runtime required by Socket.IO for non-blocking I/O |
| `smbus2` | `sensor_reader.py` | Read MPU6050 registers over Linux I²C driver |
| `numpy` | `mechanics_engine.py` | FFT (`np.fft.rfft`), Hanning window, median baseline, RMS gate |
| `scipy.signal` | `sensor_processor.py` | `butter()` designs 2nd-order Butterworth LPF coefficients; applied as a hand-rolled streaming biquad |
| `threading`, `queue` | Every layer | Producer/consumer between the I²C thread and the processor; per-layer worker threads |
| `dataclasses`, `typing` | `twin_state.py`, `material_db.py` | Structured state container + material profile records |
| `math` | Everywhere | `atan2`, `sqrt`, `degrees`, `isfinite`, etc. |
| `time`, `collections.deque` | `mechanics_engine.py`, `predictor.py` | Sliding windows for FFT buffer and TTF rate history |

### Installation

```bash
pip install flask flask-socketio eventlet smbus2 numpy scipy
```

On a Raspberry Pi running Raspbian Bookworm, use `pip install --break-system-packages …`
or a venv.

---

## 5. Frontend dependencies and their use case

| Library | Version | Source | Use case in Durian |
|---|---|---|---|
| Socket.IO client | 4.7.2 | `cdn.socket.io` | Subscribes to `sensor_data` (20 Hz) and `scenario_stream` (10 Hz) |
| Three.js | r128 | `cdnjs.cloudflare.com` | Renders the 3D building: scene, camera, renderer, lighting |
| OrbitControls | r128 | `jsdelivr.net` | Mouse-drag camera orbiting around the building model |
| OBJLoader | r128 | `jsdelivr.net` | Loads the Wavefront `.obj` building mesh from `/assets` |
| MTLLoader | r128 | `jsdelivr.net` | Loads companion `.mtl` materials for the OBJ mesh |
| Chart.js | 4.4.1 | `jsdelivr.net` | The Scenario Runner time-series chart (bending, displacement, integrity) |

All libraries are loaded from public CDNs — no bundler, no build step. The
dashboard is three flat files: `index.html`, `app.js`, `style.css`.

---

## 6. Twin state — the shared data contract

`twin_state.py` defines a single `TwinState` dataclass protected by an `RLock`.
Every producer writes via `state.update(**kwargs)`; the Flask broadcast thread
calls `state.to_dict()` at 20 Hz and emits the result.

### Field reference

| Field | Unit | Written by | Consumed by |
|---|---|---|---|
| `ax, ay, az` | g | sensor_processor | mechanics, stress, UI |
| `tilt_x, tilt_y, tilt_magnitude` | ° | sensor_processor | predictor, UI |
| `tilt_limit_{alert,severe,critical}_deg` | ° | sensor_processor | UI gauge |
| `timestamp` | ms since epoch | sensor_processor | mechanics (dt calc) |
| `sway_velocity_x, sway_velocity_y` | m/s | mechanics_engine | UI |
| `lateral_displacement` | mm | mechanics_engine | predictor, UI |
| `torsion_angle` | ° | mechanics_engine | UI |
| `dominant_frequency, baseline_frequency_hz` | Hz | mechanics_engine | predictor, UI |
| `freq_shift_pct` | % | mechanics_engine | predictor, UI |
| `active_material` | string | material_db | UI |
| `yield_strength, elastic_modulus, fatigue_limit, damping_ratio` | MPa / GPa | material_db | stress, predictor, UI |
| `bending_stress, shear_stress` | MPa | stress_model | predictor, UI |
| `stress_ratio` | 0…1 | stress_model | predictor, UI |
| `damage_percent, fatigue_cycles` | % / count | stress_model | predictor, UI |
| `integrity_score, alert_tier, evacuation_flag, resonance_warning` | 0–100 / enum / bool | predictor | UI |
| `forecast_24h` | 25 × % | predictor | UI |
| `time_to_failure_hours` | h | predictor | UI |
| `penalty_stress, penalty_fatigue, penalty_freq, penalty_tilt, penalty_disp` | points | predictor | UI weights panel |
| `w_stress, w_fatigue, w_freq, w_tilt, w_disp` | 0…1 | predictor | UI weights panel |
| `stories, floor_height, plan_width, plan_depth, structural_system` | count / m / m / m / enum | `/api/dimensions` | stress, predictor, UI |
| `building_height_m, cross_section_width_m, cross_section_depth_m, mass_estimate_kg` | m / m / m / kg | stress_model.set_dimensions | stress, scenario_engine |
| `scenario_active, scenario_params, projected_stress, projected_damage_rate` | enum / dict / MPa / %/h | scenario_stream | UI, predictor |

---

## 7. Engineering formulas used, by module

### sensor_processor.py — signal conditioning

Calibration subtracts a DC offset measured from 50 stationary samples; on the
vertical axis, 1 g of gravity is removed so all three channels read near zero
at rest.

**Butterworth low-pass filter** (scipy design, streaming biquad execution)

```
Wn = fc / (fs/2)                  # normalised cutoff
b, a = butter(order=2, Wn, "low")

y[n] = b0·x[n] + b1·x[n-1] + b2·x[n-2]
                  - a1·y[n-1] - a2·y[n-2]
```

Two independent filter chains: accel at 9.5 Hz cutoff (Nyquist-safe at fs = 20 Hz)
and displacement at 1 Hz cutoff.

**Three-axis gravity-compensated tilt** (per Analog Devices AN-1057)

```
tilt_x = atan2( fy, sqrt(fx² + fz²) )
tilt_y = atan2(-fx, sqrt(fy² + fz²) )
tilt_magnitude = sqrt(tilt_x² + tilt_y²)
```

**Drift-limit angles** derived from the total model height `H = stories · floor_height`:

```
alert_deg    = atan(1/500)   ≈ 0.115°
severe_deg   = atan(1/300)   ≈ 0.191°
critical_deg = atan(1/200)   ≈ 0.286°
```

These ratios match European code guidance for serviceability (SLS) and ultimate
drift limits used across EN 1992–1999.

### mechanics_engine.py — kinematics and modal identification

**High-pass drift compensation** (first-order RC digital equivalent, τ = 5 s):

```
α_hp = τ / (τ + dt)
v_hp[n] = α_hp · v_hp[n-1] + α_hp · (v_raw[n] - v_raw[n-1])
```

**Double trapezoidal integration** (accelerometer → displacement), with HP
compensation applied on BOTH integration stages to remove constant-bias drift.

**Silence reset**: if accel magnitude stays below 0.005 g for 2 s, integrators
snap back to zero — removes the slow-creep that plagues pure numerical
integration of noisy sensors.

**Torsion baseline and angle**: after 100 quiet samples, the system locks a
baseline `atan2(ax_base, ay_base)`; subsequent torsion is the unwrapped
difference `atan2(ax, ay) − atan2(ax_base, ay_base)` in degrees.

**FFT for dominant frequency**:

```
arr     = ax_buffer (256 samples)
arr    -= mean(arr)                 # DC removal
if rms(arr) < NOISE_FLOOR: return 0  # RMS gate: no spurious peak at rest
arr    *= hanning(256)              # leakage control
spec    = |rfft(arr)|
spec[0] = 0                          # kill residual DC
valid   = freqs ≤ 50 Hz              # band of interest
f_dom   = freqs[ argmax(spec · valid) ]
```

The baseline natural frequency is the median of FFT samples collected over the
first 30 s after start. `freq_shift_pct = |f_dom − f_base| / f_base · 100`.

### stress_model.py — mechanics of materials

Given real building geometry from the UI (`stories, floor_height, plan_width, plan_depth`),
section properties are:

```
H   = stories · floor_height
b   = plan_width
d   = plan_depth
I   = b·d³ / 12                 # rectangular second moment of area
c   = d / 2                     # extreme fibre distance
A   = b·d
```

**Euler–Bernoulli bending** (peak response to lateral acceleration):

```
V = m · a_peak · g
M = V · H
σ_bending = M · c / I           [Pa]   → /1e6 for MPa
```

**Jourawski shear** (rectangular section, max shear at the neutral axis):

```
Q       = b · (d/2)² / 2
τ_shear = V · Q / (I · b)       [Pa]   → /1e6 for MPa
```

**Stress ratio**: peak stress / governing strength (max of yield or compressive
from the active material).

**Miner's linear cumulative damage rule** with a material-specific Wöhler /
S-N curve:

```
N_i        = N_ref · (σ_ref / σ_peak)^m         # allowable cycles at σ_peak
n_interval = f_dom · Δt                          # cycles per sample period
ΔD         = n_interval / N_i
D         += ΔD                                  # clamped to [0, 1]
```

Failure is defined by `D = 1` (Palmgren–Miner). `damage_percent = D · 100`.

### predictor.py — prognosis

**Weighted composite integrity** (starts at 100, subtracts five penalties):

```
live_stress  = min(stress_ratio, 1)                · 100 · w_stress
live_fatigue = min(D, 1)                           · 100 · w_fatigue
live_freq    = min(freq_shift_pct / 20, 1)         · 100 · w_freq
live_tilt    = min(tilt_magnitude / tilt_crit, 1)  · 100 · w_tilt
live_disp    = min(disp_mm / disp_limit_mm, 1)     · 100 · w_disp

integrity = 100 − peak_stress − peak_fatigue
               − peak_freq   − peak_tilt
               − peak_disp
```

Each of the transient penalties (stress, freq, tilt, disp) is **peak-held** at
module scope — once the structure has seen damage, the score does not recover
when the sensor returns to rest. Only `reset_baseline()` (called by
`/api/calibrate` and `/api/reset_damage`) clears the peaks. The fatigue
penalty is already monotonic via Miner's rule.

Weights `w_stress / w_fatigue / w_disp` come from the active material profile;
`w_freq / w_tilt` are global constants (0.20 / 0.15).

**Alert tiers**: ≥ 80 nominal, ≥ 60 watch, ≥ 40 warning, ≥ 20 critical, else
evacuate. The evacuation tier sets `evacuation_flag`.

**Time-to-failure** from the last 60 s of damage rate:

```
rate = (D_now − D_{now-60s}) / 60     [per second]
TTF  = (1 − D_now) / rate             [seconds]  → /3600 for hours
```

**24-hour forecast**: 25 × hourly linear projection
`integrity_now − i · rate · 3600 · 100`, clamped to ≥ 0.

### scenario_engine.py — deterministic what-if calculations

Every scenario reads live building geometry and active material. All outputs
are in MPa and comparable directly to `mat.yield_strength`.

**Wind load** (lateral drag on frontal area):

```
ρ_air = 1.225 kg/m³
C_d   = 1.3   (flat bluff body)
A     = H · plan_width
v     = wind_speed_kmh / 3.6
F     = 0.5 · ρ · C_d · A · v²
M     = F · H
σ     = M · c / I                 [MPa]
```

**Seismic load** (empirical PGA attenuation, then static equivalent):

```
PGA   = 0.015 · 10^(0.5·M) / d_km^1.5     [g]
F     = m · PGA · g
σ     = (F · H) · c / I                    [MPa]
```

**Overload** (extra floors — axial):

```
N_dead = m_floor · n_floors · g
N_live = q_live · A_floor · occupancy · n_floors · g
σ_axial = (N_dead + N_live) / A            [MPa]
```

Uses `FLOOR_DEAD_LOAD_KG = 3000 kg/floor`, `LIVE_LOAD_KG_PER_M2 = 200 kg/m²`,
`FLOOR_AREA_M2 = 9 m²` (EN 1991-1-1 Category A residential).

**Thermal stress** (fully restrained elongation):

```
α     = 12·10⁻⁶ 1/°C       (concrete/steel composite default)
ε     = α · |ΔT|
σ     = E · ε              [MPa]
```

**Flood — hydrostatic lateral load**:

```
ρ_w       = 1000 kg/m³
p_avg     = ρ_w · g · (h_water / 2)
F_lateral = p_avg · (h_water · plan_width)
M         = F · (h_water / 3)                # at triangular load centroid
σ         = M · c / I                        [MPa]
```

All five compute `total_projected_stress = σ_bending_live + σ_additional` and a
`safe` flag `total < mat.yield_strength`. Damage rate per hour is backed out
from the fatigue-limit-exceedance ratio when `σ > mat.fatigue_limit`.

### scenario_stream.py — 10-second animated what-if

Wraps `scenario_engine` in a streaming thread. Uses a smoothstep ease
`t·t·(3−2t)` to ramp bending and displacement from baseline to target across
100 frames (10 Hz · 10 s), and writes `projected_stress` / `projected_damage_rate`
into `twin_state` for the whole run. Intensity (0–1 from the UI slider) maps to:

| Kind | 0 → 1 maps to |
|---|---|
| wind | 20 → 200 km/h |
| seismic | M 4 → M 8.5, distance 50 → 10 km |
| overload | 1 → 5 extra floors, 10% → 100% occupancy |
| thermal | 0 → 60 °C ΔT |
| flood | 0 → 5 m water depth |

---

## 8. Material database — `material_db.py`

Every profile contains the parameters needed by the stress layer, the
fatigue model (S-N), and the integrity weighting.

| Material | Standard | f_yk (MPa) | f_ck (MPa) | E (GPa) | σ_ref (MPa) | N_ref | m (S-N slope) | w_s / w_f / w_d |
|---|---|---|---|---|---|---|---|---|
| reinforced_concrete | EN 1992-1-1 C30/37 | 30 | 30 | 33 | 9 | 1 · 10⁶ | 10 | 0.35 / 0.20 / 0.10 |
| structural_steel | EN 1993-1-1 / 1-9 S275 | 275 | 275 | 210 | 80 | 2 · 10⁶ | 3 | 0.25 / 0.35 / 0.10 |
| glulam_timber | EN 1995-1-1 GL24h | 24 | 24 | 11.5 | 7 | 1 · 10⁶ | 8 | 0.25 / 0.15 / 0.25 |
| unreinforced_masonry | EN 1996-1-1 | 3.5 | 5.0 | 5.5 | 1.2 | 1 · 10⁶ | 12 | 0.40 / 0.10 / 0.25 |
| prestressed_concrete | EN 1992-1-1 C50/60 | 50 | 50 | 37 | 15 | 1 · 10⁶ | 10 | 0.30 / 0.25 / 0.10 |
| aluminium_alloy | EN 1999-1-1 6082-T6 | 240 | 240 | 70 | 70 | 5 · 10⁶ | 4 | 0.25 / 0.35 / 0.10 |

The slope `m` reflects fatigue sensitivity: low `m` (steel/aluminium) means
rapid damage accumulation above the endurance limit; high `m` (masonry)
means very long fatigue life but catastrophic yield behaviour — which is
why masonry's stress weight is highest (0.40) while its fatigue weight is
lowest (0.10).

---

## 9. HTTP / REST API

All endpoints are served by `server.py` on port 5000.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serves the dashboard |
| `GET` | `/api/data` | Single JSON snapshot of `twin_state` |
| `POST` | `/api/material` | Body: `{ "material": "structural_steel" }` — change active material |
| `POST` | `/api/dimensions` | Body: `{ height, width, depth, mass, stories, floor_height, plan_width, plan_depth, structural_system }` |
| `POST` | `/api/calibrate` | Re-calibrate sensor offsets; clears damage, integrity peaks, mechanics |
| `POST` | `/api/reset_damage` | Clear only damage + integrity peaks |
| `POST` | `/api/scenario` | Body: `{ "scenario": "wind_load", "wind_speed_kmh": 90 }` — one-shot calculation |
| `DELETE` | `/api/scenario` | Clear any active scenario state |
| `GET` | `/api/scenario/all` | Run every scenario with default params, return a dict |
| `POST` | `/run_scenario` | Body: `{ "scenario": "wind", "intensity": 0.5 }` — launches the 10-second animated simulation |
| `POST` | `/stop_scenario` | Abort the streaming scenario |
| `GET` | `/assets/<path>` | Serves the 3D OBJ/MTL model from `../3ddio/` |

---

## 10. Socket.IO events

| Event | Direction | Payload | Frequency |
|---|---|---|---|
| `connect` | client → server | — | once |
| `sensor_data` | server → client | full `twin_state.to_dict()` | 20 Hz |
| `scenario_stream` | server → client | `{ phase: "start"/"frame"/"end"/"error", … }` | 10 Hz during a scenario |

Scenario `start` payload carries `target_stress_mpa`, `target_ratio_pct`,
`yield_strength_mpa`, `material`, `safe`, `summary`, `n_steps`. Each
`frame` carries `bending_stress`, `shear_stress`, `stress_ratio`,
`lateral_displacement`, `damage_percent`, `integrity_score`, `alert_tier`,
`progress`, `step`, `t_s`.

---

## 11. Running Durian

```bash
cd digital-twin
python server.py
```

Boot banner prints which layers loaded and the local/network URLs.
On a machine without I²C hardware, `sensor_reader` logs a FATAL and
exits its thread — the rest of the stack still runs on the last
values in `twin_state`, so the dashboard, scenarios, and 3D view
remain usable for development.

### First-use procedure

1. Open `http://<host>:5000` in a browser.
2. Place the physical model on a level surface and do not touch it.
3. Click **Calibrate** — this re-measures the gravity offsets for all three
   axes, resets the torsion baseline, the frequency baseline, and the
   integrity peak-holds.
4. Enter the real building geometry in the Building Model panel: number of
   stories, floor height, plan width / depth, total mass, structural
   system. Click **Apply**. The stress / scenario layers now use your
   geometry.
5. Select the right material from the dropdown.
6. You are live.

### Tuning reference (edit at the top of each file)

| Constant | File | Default | Meaning |
|---|---|---|---|
| `SAMPLE_RATE_HZ` | sensor_processor | 20 | Sensor polling rate (must match `sensor_reader` POLL_INTERVAL) |
| `ACCEL_CUTOFF_HZ` | sensor_processor | 9.5 | Butterworth accel LPF cutoff (Nyquist-safe) |
| `DISPLACEMENT_CUTOFF_HZ` | sensor_processor | 1.0 | Butterworth displacement LPF cutoff |
| `ACCEL_DEADBAND_G` | sensor_processor | 0.005 | Zero accel channels below this threshold at rest |
| `TILT_DEADBAND_DEG` | sensor_processor | 0.10 | Zero tilt readings below this |
| `CALIBRATION_SAMPLES` | sensor_processor | 50 | Number of samples averaged during /api/calibrate |
| `HP_TAU_SECONDS` | mechanics_engine | 5.0 | High-pass time constant for drift rejection |
| `NOISE_FLOOR_G` | mechanics_engine | 0.005 | RMS floor for FFT + silence reset |
| `NOISE_SILENT_SECONDS` | mechanics_engine | 2.0 | Silence length that triggers integrator reset |
| `FFT_BUFFER_SIZE` | mechanics_engine | 256 | Samples in the FFT ring |
| `FFT_MAX_FREQ_HZ` | mechanics_engine | 50.0 | Cap for dominant frequency search band |
| `BASELINE_FREQ_SECONDS` | mechanics_engine | 30.0 | Window to lock the natural frequency baseline |
| `ACCEL_DEADBAND_G` | stress_model | 0.002 | Below this, emit zero stress and skip Miner accumulation |
| `W_FREQ / W_TILT` | predictor | 0.20 / 0.15 | Global integrity weights for frequency-shift and tilt penalties |
| `FREQ_SHIFT_NORMALIZATION_PCT` | predictor | 20.0 | Frequency-shift %  that scores 100% of its weight |
| `TTF_HISTORY_SECONDS` | predictor | 60.0 | Rolling window used to compute the damage rate for TTF |

---

## 12. Signal processing pipeline in one page

```
raw g (20 Hz)  ──►  offset-calibrated  ──►  Butterworth order-2 LPF (9.5 Hz cutoff)
                                                       │
                                                       ▼
                          deadbanded to 0 below 0.005 g
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    ▼                  ▼                  ▼
                    atan2 gravity tilt        trapezoidal         ax_ring 256-sample
                      (deadbanded 0.1°)        integration             ▼
                                                │                hanning · rFFT
                                    HP drift compensation (τ=5s)
                                            (both stages)        RMS-gate at 0.005 g
                                                │                peak freq ≤ 50 Hz
                                                ▼                       │
                                   silence reset if <0.005 g / 2 s      │
                                                │                       │
                                                ▼                       ▼
                                    lateral displacement         dominant_frequency
                                     (after 1 Hz LPF, mm)        baseline locked t=30s
                                                │                freq_shift_pct
                                                │                       │
                                                └──────────┬────────────┘
                                                           ▼
                                              stress_model + predictor
```

---

## 13. Safety and engineering caveats

Durian is a structural-health monitoring prototype. The formulas are textbook
and the parameters come from published codes, but:

*  The MPU6050 is a ±2 g MEMS accelerometer with roughly ±0.1 °/√Hz tilt
   noise — fine for a tabletop model, insufficient for a real building.
*  Derived displacement from double-integrated acceleration is inherently
   drift-prone; the HP compensation and silence reset mitigate but do not
   eliminate this. Use tilt and frequency shift as primary indicators.
*  The Miner's-rule damage model assumes a single dominant stress cycle per
   modal period. Multi-axial loading and rainflow counting are not
   implemented.
*  The integrity score is a weighted heuristic to aggregate heterogeneous
   signals into one dashboard number. It is not a design-code demand/capacity
   ratio.

---

## 14. References

*  EN 1991-1-1 — Actions on structures — General actions: densities and live loads.
*  EN 1992-1-1 — Design of concrete structures (C30/37, C50/60 classes).
*  EN 1993-1-1 / EN 1993-1-9 — Steel structures — general rules and fatigue.
*  EN 1995-1-1 — Timber structures (GL24h glulam).
*  EN 1996-1-1 — Masonry structures.
*  EN 1999-1-1 — Aluminium structures (6082-T6).
*  Analog Devices AN-1057 — Using accelerometers for inclination sensing.
*  Palmgren (1924) / Miner (1945) — linear cumulative damage rule.
*  Jourawski (1856) — shear stress distribution in rectangular beams.
*  Oppenheim & Schafer — Discrete-Time Signal Processing (Butterworth IIR design).
