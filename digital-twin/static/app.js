(function () {
    "use strict";

    const SWAY_WINDOW = 40;
    const SWAY_RANGE = 1.0;
    const SIGNIFICANT_THRESHOLD = 0.3;
    const RATE_INTERVAL_MS = 1000;
    const GAUGE_CIRC = 2 * Math.PI * 58;
    const TIER_CLASSES = [
        "tier-nominal", "tier-watch", "tier-warning", "tier-critical", "tier-evacuate"
    ];

    const el = {
        valX: document.getElementById("val-x"),
        valY: document.getElementById("val-y"),
        valZ: document.getElementById("val-z"),
        peakX: document.getElementById("peak-x"),
        peakY: document.getElementById("peak-y"),
        peakZ: document.getElementById("peak-z"),
        valTilt: document.getElementById("val-tilt"),
        valHz: document.getElementById("val-hz"),
        statusDot: document.getElementById("status-dot"),
        statusText: document.getElementById("status-text"),
        resetPeaks: document.getElementById("reset-peaks"),
        sparkline: document.getElementById("sparkline-container"),

        swayVelX: document.getElementById("val-sway-x"),
        swayVelY: document.getElementById("val-sway-y"),
        disp: document.getElementById("val-disp"),
        torsion: document.getElementById("val-torsion"),
        domFreq: document.getElementById("val-dom-freq"),
        baselineFreq: document.getElementById("val-baseline-freq"),
        freqShift: document.getElementById("val-freq-shift"),
        freqHealthDot: document.getElementById("freq-health-dot"),

        selMaterial: document.getElementById("sel-material"),
        headerMaterial: document.getElementById("header-material"),
        headerTier: document.getElementById("header-tier"),
        yieldVal: document.getElementById("val-yield"),
        emod: document.getElementById("val-emod"),
        fatigue: document.getElementById("val-fatigue"),
        damping: document.getElementById("val-damping"),

        bend: document.getElementById("val-bend"),
        shear: document.getElementById("val-shear"),
        barStressRatio: document.getElementById("bar-stress-ratio"),
        stressRatio: document.getElementById("val-stress-ratio"),
        damage: document.getElementById("val-damage"),
        cycles: document.getElementById("val-cycles"),
        btnResetDamage: document.getElementById("btn-reset-damage"),

        integrity: document.getElementById("val-integrity"),
        tier: document.getElementById("val-tier"),
        resonance: document.getElementById("val-resonance"),
        resonanceBadge: document.getElementById("resonance-badge"),
        evac: document.getElementById("val-evac"),
        ttf: document.getElementById("val-ttf"),
        gaugeRing: document.getElementById("gauge-ring"),

        scenarioName: document.getElementById("val-scenario"),
        projStress: document.getElementById("val-proj-stress"),
        btnClearScenario: document.getElementById("btn-clear-scenario"),

        btnCalibrate: document.getElementById("btn-calibrate"),

        btnSyncBuilding: document.getElementById("btn-sync-building"),
        inBFloors: document.getElementById("in-b-floors"),
        inBFloorHeight: document.getElementById("in-b-floor-height"),
        inBWidth: document.getElementById("in-b-width"),
        inBDepth: document.getElementById("in-b-depth"),
        inBStructure: document.getElementById("in-b-structure"),
        valBHeight: document.getElementById("val-b-height"),
        valBMass: document.getElementById("val-b-mass"),
        ttfHuman: document.getElementById("val-ttf-human"),

        tgZoneGreen: document.getElementById("tg-zone-green"),
        tgZoneYellow: document.getElementById("tg-zone-yellow"),
        tgZoneRed: document.getElementById("tg-zone-red"),
        tgMarker: document.getElementById("tg-marker"),
        tgAlert: document.getElementById("tg-alert"),
        tgSevere: document.getElementById("tg-severe"),
        tgCritical: document.getElementById("tg-critical"),

        wbarStress: document.getElementById("wbar-stress"),
        wbarFatigue: document.getElementById("wbar-fatigue"),
        wbarFreq: document.getElementById("wbar-freq"),
        wbarTilt: document.getElementById("wbar-tilt"),
        wbarDisp: document.getElementById("wbar-disp"),
        wvalStress: document.getElementById("wval-stress"),
        wvalFatigue: document.getElementById("wval-fatigue"),
        wvalFreq: document.getElementById("wval-freq"),
        wvalTilt: document.getElementById("wval-tilt"),
        wvalDisp: document.getElementById("wval-disp"),
        weightsNote: document.getElementById("weights-note"),

        infoModal: document.getElementById("info-modal"),
        infoModalBackdrop: document.getElementById("info-modal-backdrop"),
        infoModalClose: document.getElementById("info-modal-close"),
        infoModalTitle: document.getElementById("info-modal-title"),
        infoModalWhat: document.getElementById("info-modal-what"),
        infoModalFormula: document.getElementById("info-modal-formula"),
        infoModalLimit: document.getElementById("info-modal-limit"),
        infoModalWhy: document.getElementById("info-modal-why"),
    };

    const local = {
        peaks: { x: 0, y: 0, z: 0 },
        swayBuffer: [],
        packetCount: 0,
        connected: false,
        lastMaterial: "reinforced_concrete",
        lastStructural: "concrete",
        lastLimits: { alert: 0, severe: 0, critical: 0 },
        lastMatrial: null,
    };

    function setStatus(cls, text) {
        if (!el.statusDot || !el.statusText) return;
        el.statusDot.classList.remove("status-connected", "status-disconnected", "status-warning");
        el.statusDot.classList.add(cls);
        el.statusText.textContent = text;
    }

    function formatSigned(v, d) {
        const s = v >= 0 ? "+" : "";
        return s + v.toFixed(d);
    }

    function num(v, fallback) {
        return typeof v === "number" && isFinite(v) ? v : fallback;
    }

    function updateAxisValue(element, value) {
        if (!element) return;
        element.textContent = formatSigned(value, 2);
        element.style.color = Math.abs(value) > SIGNIFICANT_THRESHOLD
            ? "var(--danger)" : "var(--accent)";
    }

    function updatePeaks(x, y, z) {
        const ax = Math.abs(x), ay = Math.abs(y), az = Math.abs(z);
        if (ax > local.peaks.x) local.peaks.x = ax;
        if (ay > local.peaks.y) local.peaks.y = ay;
        if (az > local.peaks.z) local.peaks.z = az;
        if (el.peakX) el.peakX.textContent = local.peaks.x.toFixed(2);
        if (el.peakY) el.peakY.textContent = local.peaks.y.toFixed(2);
        if (el.peakZ) el.peakZ.textContent = local.peaks.z.toFixed(2);
    }

    function resetPeaks() {
        local.peaks = { x: 0, y: 0, z: 0 };
        if (el.peakX) el.peakX.textContent = "0.00";
        if (el.peakY) el.peakY.textContent = "0.00";
        if (el.peakZ) el.peakZ.textContent = "0.00";
    }

    function updateSparkline(v) {
        if (!el.sparkline) return;
        local.swayBuffer.push(v);
        if (local.swayBuffer.length > SWAY_WINDOW) local.swayBuffer.shift();
        const W = 200, H = 48, mid = H / 2;
        if (local.swayBuffer.length < 2) { el.sparkline.innerHTML = ""; return; }
        const step = W / (SWAY_WINDOW - 1);
        const points = local.swayBuffer.map((v, i) => {
            const c = Math.max(-SWAY_RANGE, Math.min(SWAY_RANGE, v));
            const px = i * step;
            const py = mid - (c / SWAY_RANGE) * (H / 2);
            return px.toFixed(2) + "," + py.toFixed(2);
        }).join(" ");
        el.sparkline.innerHTML =
            '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">' +
            '<polyline points="' + points + '" fill="none" stroke="#00d4ff" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
            '</svg>';
    }

    function tierFromScore(score) {
        if (score >= 80) return "nominal";
        if (score >= 60) return "watch";
        if (score >= 40) return "warning";
        if (score >= 20) return "critical";
        return "evacuate";
    }

    function tierColor(tier) {
        return {
            nominal:  "#22c55e",
            watch:    "#00d4ff",
            warning:  "#f59e0b",
            critical: "#fb923c",
            evacuate: "#ef4444",
        }[tier] || "#22c55e";
    }

    function applyTierBadge(element, tier) {
        if (!element) return;
        TIER_CLASSES.forEach(c => element.classList.remove(c));
        element.classList.add("tier-" + tier);
        element.textContent = tier.toUpperCase();
    }

    function updateGauge(score, tier) {
        if (!el.gaugeRing) return;
        const pct = Math.max(0, Math.min(100, score)) / 100;
        const offset = GAUGE_CIRC * (1 - pct);
        el.gaugeRing.setAttribute("stroke-dashoffset", offset.toFixed(2));
        el.gaugeRing.setAttribute("stroke", tierColor(tier));
    }

    function tickSampleRate() {
        if (el.valHz) el.valHz.textContent = String(local.packetCount);
        local.packetCount = 0;
    }
    setInterval(tickSampleRate, RATE_INTERVAL_MS);

    function apiPost(url, body) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body || {}),
        }).then(r => r.json());
    }

    if (el.resetPeaks) el.resetPeaks.addEventListener("click", resetPeaks);

    if (el.selMaterial) {
        el.selMaterial.addEventListener("change", () => {
            apiPost("/api/material", { material: el.selMaterial.value }).catch(console.error);
        });
    }

    if (el.btnCalibrate) {
        el.btnCalibrate.addEventListener("click", () => {
            el.btnCalibrate.disabled = true;
            el.btnCalibrate.textContent = "Calibrating...";
            apiPost("/api/calibrate", {})
                .finally(() => {
                    el.btnCalibrate.disabled = false;
                    el.btnCalibrate.textContent = "Recalibrate";
                });
        });
    }

    if (el.btnResetDamage) {
        el.btnResetDamage.addEventListener("click", () => {
            apiPost("/api/reset_damage", {}).catch(console.error);
        });
    }

    const inIntensity = document.getElementById("in-intensity");
    const valIntensity = document.getElementById("val-intensity");
    const btnStopScenario = document.getElementById("btn-stop-scenario");
    const scenarioBtns = document.querySelectorAll(".scenario-btn[data-sim]");

    function intensityValue() {
        return inIntensity ? (parseInt(inIntensity.value, 10) / 100) : 0.5;
    }
    function paintIntensity() {
        if (valIntensity) valIntensity.textContent = intensityValue().toFixed(2);
    }
    if (inIntensity) inIntensity.addEventListener("input", paintIntensity);
    paintIntensity();

    scenarioBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const kind = btn.getAttribute("data-sim");
            scenarioBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            apiPost("/run_scenario", {
                scenario: kind,
                intensity: intensityValue(),
            }).catch(console.error);
        });
    });

    if (btnStopScenario) {
        btnStopScenario.addEventListener("click", () => {
            apiPost("/stop_scenario", {}).catch(console.error);
        });
    }

    const STRUCT_DENSITY = {
        concrete: 420.0,
        steel:    220.0,
        masonry:  550.0,
        timber:   160.0,
    };

    function buildingSpec() {
        const floors = Math.max(1, parseInt(el.inBFloors && el.inBFloors.value, 10) || 1);
        const floorH = Math.max(2.0, parseFloat(el.inBFloorHeight && el.inBFloorHeight.value) || 3.3);
        const width  = Math.max(1.0, parseFloat(el.inBWidth && el.inBWidth.value) || 10.0);
        const depth  = Math.max(1.0, parseFloat(el.inBDepth && el.inBDepth.value) || 10.0);
        const stype  = (el.inBStructure && el.inBStructure.value) || "concrete";
        const density = STRUCT_DENSITY[stype] || STRUCT_DENSITY.concrete;
        const height = floors * floorH;
        const mass = width * depth * height * density;
        return { floors, floorH, width, depth, stype, height, mass };
    }

    function radToDeg(x) { return x * 180 / Math.PI; }

    function repaintBuildingSpec() {
        const s = buildingSpec();
        if (el.valBHeight) el.valBHeight.textContent = s.height.toFixed(1);
        if (el.valBMass) el.valBMass.textContent = (s.mass / 1000).toFixed(1);
        const alertDeg = radToDeg(Math.atan(1 / 500));
        const severeDeg = radToDeg(Math.atan(1 / 300));
        const criticalDeg = radToDeg(Math.atan(1 / 200));
        updateTiltGauge(0, alertDeg, severeDeg, criticalDeg);
        local.lastStructural = s.stype;
        updateWeightsNote();
    }

    [el.inBFloors, el.inBFloorHeight, el.inBWidth, el.inBDepth, el.inBStructure].forEach(inp => {
        if (inp) inp.addEventListener("input", repaintBuildingSpec);
    });
    repaintBuildingSpec();

    if (el.btnSyncBuilding) {
        el.btnSyncBuilding.addEventListener("click", () => {
            const s = buildingSpec();
            const body = {
                height: s.height,
                mass: s.mass,
                width: s.width,
                depth: s.depth,
                stories: s.floors,
                floor_height: s.floorH,
                plan_width: s.width,
                plan_depth: s.depth,
                structural_system: s.stype,
            };
            apiPost("/api/dimensions", body).then(res => {
                if (res.status === "ok") {
                    el.btnSyncBuilding.textContent = "Synced!";
                    setTimeout(() => el.btnSyncBuilding.textContent = "Sync to Twin", 1500);
                }
            }).catch(console.error);
        });
    }

    function updateTiltGauge(tiltMag, alertDeg, severeDeg, criticalDeg) {
        if (!el.tgMarker || !el.tgZoneGreen || !el.tgZoneYellow || !el.tgZoneRed) return;
        const scaleMax = Math.max(criticalDeg * 1.2, 0.5);
        const pct = (deg) => Math.max(0, Math.min(100, (deg / scaleMax) * 100));
        const gEnd = pct(alertDeg);
        const yEnd = pct(severeDeg);
        const rEnd = pct(criticalDeg);
        el.tgZoneGreen.style.left = "0%";
        el.tgZoneGreen.style.width = gEnd.toFixed(2) + "%";
        el.tgZoneYellow.style.left = gEnd.toFixed(2) + "%";
        el.tgZoneYellow.style.width = Math.max(0, yEnd - gEnd).toFixed(2) + "%";
        el.tgZoneRed.style.left = yEnd.toFixed(2) + "%";
        el.tgZoneRed.style.width = Math.max(0, rEnd - yEnd).toFixed(2) + "%";
        el.tgMarker.style.left = pct(tiltMag).toFixed(2) + "%";
        if (el.tgAlert) el.tgAlert.textContent = alertDeg.toFixed(3) + "\u00B0";
        if (el.tgSevere) el.tgSevere.textContent = severeDeg.toFixed(3) + "\u00B0";
        if (el.tgCritical) el.tgCritical.textContent = criticalDeg.toFixed(3) + "\u00B0";
        local.lastLimits = { alert: alertDeg, severe: severeDeg, critical: criticalDeg };
    }

    function updateFreqHealth(dom, base, shiftPct) {
        if (el.baselineFreq) el.baselineFreq.textContent = base.toFixed(3);
        if (el.freqShift) el.freqShift.textContent = shiftPct.toFixed(2);
        if (el.freqHealthDot) {
            el.freqHealthDot.classList.remove("health-dot-green", "health-dot-yellow", "health-dot-red");
            let cls = "health-dot-green";
            if (shiftPct > 15) cls = "health-dot-red";
            else if (shiftPct > 5) cls = "health-dot-yellow";
            el.freqHealthDot.classList.add(cls);
        }
    }

    function setWeightBar(barEl, valEl, contribution, color) {
        if (barEl) {
            barEl.style.width = Math.max(0, Math.min(100, contribution)).toFixed(1) + "%";
            if (color) barEl.style.background = color;
        }
        if (valEl) valEl.textContent = contribution.toFixed(1) + " / 100";
    }

    function updateWeightsNote() {
        if (!el.weightsNote) return;
        el.weightsNote.textContent = "Weights adjusted for " + local.lastMaterial + " / " + local.lastStructural;
    }

    function updateWeightsPanel(pS, pF, pFr, pT, pD) {
        setWeightBar(el.wbarStress,  el.wvalStress,  pS,  "var(--warning)");
        setWeightBar(el.wbarFatigue, el.wvalFatigue, pF,  "var(--danger)");
        setWeightBar(el.wbarFreq,    el.wvalFreq,    pFr, "var(--accent)");
        setWeightBar(el.wbarTilt,    el.wvalTilt,    pT,  "#fb923c");
        setWeightBar(el.wbarDisp,    el.wvalDisp,    pD,  "#a78bfa");
    }

    const INFO = {
        tilt_angle: {
            title: "Tilt Angle",
            what: "Inclinarea structurii calculată din accelerometru cu compensare gravitațională pe 3 axe.",
            formula: "tilt_x = atan2(a_y, sqrt(a_x^2 + a_z^2))\ntilt_y = atan2(-a_x, sqrt(a_y^2 + a_z^2))\ntilt_magnitude = sqrt(tilt_x^2 + tilt_y^2)",
            limit: (s) => "Alert " + s.lAlert + "°, Severe " + s.lSevere + "°, Critical " + s.lCritical + "° (din H/500, H/300, H/200)",
            why: "Înclinarea excesivă indică o pierdere ireversibilă de verticalitate și un risc crescut de instabilitate globală.",
        },
        sway_velocity: {
            title: "Sway Velocity",
            what: "Viteza laterală de oscilație, obținută prin integrarea accelerației cu high-pass drift compensation.",
            formula: "v = ∫ a dt\nv_hp = (τ/(τ+dt)) · (v_hp_prev + v - v_prev)",
            limit: () => "Depinde de materialul și sistemul structural; urmărește tendința, nu o limită fixă.",
            why: "Viteze laterale mari semnalează vibrație puternică și posibilă apropiere de rezonanță.",
        },
        lateral_displacement: {
            title: "Lateral Displacement",
            what: "Deplasarea laterală, prin dublă integrare a accelerației cu high-pass aplicat de două ori.",
            formula: "v = ∫ a dt  (cu HP)\nu = ∫ v dt  (cu HP)\n|u| = √(u_x² + u_y²)",
            limit: (s) => "Limită admisă ≈ " + s.dispLim.toFixed(1) + " mm (H/250)",
            why: "Depășirea limitei de deplasare poate duce la fisurare, pierderi funcționale și în final colaps.",
        },
        torsion: {
            title: "Torsion",
            what: "Moment torsional estimat din asimetria vectorului de accelerație față de baseline.",
            formula: "θ = atan2(a_x, a_y) − atan2(a_x0, a_y0)",
            limit: () => "Tipic < 2° nominal; > 5° indică solicitare critică asimetrică.",
            why: "Efectele torsionale concentrează eforturile în colțuri și elemente de colț, accelerând ruperea.",
        },
        dominant_frequency: {
            title: "Dominant Frequency",
            what: "Frecvența dominantă de oscilație extrasă prin FFT (fereastră Hanning, 256 sample-uri).",
            formula: "X(k) = FFT(hanning(x[n]))\nf_dom = argmax |X(k)|, k>0, f ≤ 50 Hz\nshift% = |f − f_baseline| / f_baseline · 100",
            limit: (s) => "Baseline " + s.baselineFreq.toFixed(3) + " Hz — shift > 15% indică degradare semnificativă.",
            why: "Scăderea frecvenței naturale arată pierdere de rigiditate — un indicator precoce de avarie structurală.",
        },
        bending_stress: {
            title: "Bending Stress",
            what: "Efortul normal maxim produs de momentul încovoietor pe secțiunea clădirii.",
            formula: "σ = M·c / I\nM = m · a_peak · g · H,  I = b·d³/12,  c = d/2",
            limit: (s) => "Limită material: " + s.matLimit.toFixed(1) + " MPa (" + s.material + ")",
            why: "Când σ depășește limita, apar fisuri macroscopice și pierdere rapidă de capacitate portantă.",
        },
        shear_stress: {
            title: "Shear Stress",
            what: "Efortul tangențial maxim prin formula Jourawski pentru secțiune dreptunghiulară.",
            formula: "τ = V·Q / (I·b)\nV = m · a_peak · g,  Q = b·(d/2)²/2",
            limit: (s) => "Limită tangențială ≈ 0.6 × " + s.matLimit.toFixed(1) + " MPa pentru " + s.material,
            why: "Cedarea la forfecare este bruscă și fragilă — un mod de rupere deosebit de periculos.",
        },
        stress_ratio: {
            title: "Stress Ratio",
            what: "Raportul dintre efortul maxim și limita materialului (yield sau compressive).",
            formula: "ratio = max(σ, τ) / f_limit",
            limit: (s) => "f_limit = " + s.matLimit.toFixed(1) + " MPa — țintă < 0.5, critical > 0.75.",
            why: "Raportul exprimă cât de aproape ești de cedare — baza oricărei verificări la stare limită ultimă.",
        },
        fatigue_damage: {
            title: "Fatigue Damage (Miner)",
            what: "Degradare cumulată prin regula lui Miner folosind curba S-N a materialului.",
            formula: "N_i = N_ref · (σ_ref / σ_i)^m\nD = Σ n_i / N_i",
            limit: (s) => "D = 1.0 înseamnă cedare. Material: " + s.material + " (m=" + s.snSlope + ")",
            why: "Oboseala apare sub solicitări repetate și duce la rupere chiar sub limita elastică.",
        },
        integrity_score: {
            title: "Integrity Score",
            what: "Scor compozit ponderat (0–100) care pornește de la 100 și scade cu fiecare contribuție de risc.",
            formula: "I = 100 − Σ w_i · p_i\nw depinde de material și sistem structural",
            limit: () => "≥80 nominal, 60–80 watch, 40–60 warning, 20–40 critical, <20 evacuate.",
            why: "Este indicatorul unic de sănătate care agregă toate semnalele într-o decizie acționabilă.",
        },
        time_to_failure: {
            title: "Time to Failure",
            what: "Estimarea timpului rămas până la D=1, pe baza ratei de creștere a fatigue damage din ultimele 60s.",
            formula: "damage_rate = (D(t) − D(t−60s)) / 60\nTTF = (1 − D) / damage_rate",
            limit: () => "Depinde de regimul de solicitare curent — se recalculează continuu.",
            why: "Permite planificarea acțiunilor (evacuare, oprire) înainte ca cedarea să devină iminentă.",
        },
    };

    function buildInfoContext() {
        const snap = local.lastSnap || {};
        const alertDeg = num(local.lastLimits.alert, radToDeg(Math.atan(1 / 500)));
        const severeDeg = num(local.lastLimits.severe, radToDeg(Math.atan(1 / 300)));
        const criticalDeg = num(local.lastLimits.critical, radToDeg(Math.atan(1 / 200)));
        const matLimitRaw = num(snap.yield_strength, 0);
        return {
            lAlert: alertDeg.toFixed(3),
            lSevere: severeDeg.toFixed(3),
            lCritical: criticalDeg.toFixed(3),
            dispLim: num(snap.disp_limit_mm, 40.0),
            material: snap.active_material || local.lastMaterial,
            matLimit: matLimitRaw,
            baselineFreq: num(snap.baseline_frequency_hz, 0),
            snSlope: num(snap.sn_slope, "?"),
        };
    }

    function openInfo(key) {
        const entry = INFO[key];
        if (!entry || !el.infoModal) return;
        const ctx = buildInfoContext();
        if (el.infoModalTitle) el.infoModalTitle.textContent = entry.title;
        if (el.infoModalWhat) el.infoModalWhat.textContent = entry.what;
        if (el.infoModalFormula) el.infoModalFormula.textContent = entry.formula;
        if (el.infoModalLimit) el.infoModalLimit.textContent = typeof entry.limit === "function" ? entry.limit(ctx) : entry.limit;
        if (el.infoModalWhy) el.infoModalWhy.textContent = entry.why;
        el.infoModal.classList.add("open");
        el.infoModal.setAttribute("aria-hidden", "false");
    }

    function closeInfo() {
        if (!el.infoModal) return;
        el.infoModal.classList.remove("open");
        el.infoModal.setAttribute("aria-hidden", "true");
    }

    document.addEventListener("click", (e) => {
        const t = e.target;
        if (t instanceof HTMLElement && t.classList.contains("info-btn")) {
            const key = t.getAttribute("data-info");
            if (key) openInfo(key);
        }
    });
    if (el.infoModalBackdrop) el.infoModalBackdrop.addEventListener("click", closeInfo);
    if (el.infoModalClose) el.infoModalClose.addEventListener("click", closeInfo);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeInfo();
    });

    setStatus("status-disconnected", "Disconnected");

    const socket = io({
        reconnection: true,
        reconnectionDelay: 2000,
        reconnectionDelayMax: 2000,
        reconnectionAttempts: Infinity,
        transports: ["websocket", "polling"],
    });

    socket.on("connect", () => {
        local.connected = true;
        setStatus("status-connected", "Live");
    });
    socket.on("disconnect", () => {
        local.connected = false;
        setStatus("status-disconnected", "Disconnected");
    });
    socket.io.on("reconnect_attempt", () => {
        if (!local.connected) setStatus("status-warning", "Reconnecting...");
    });
    socket.io.on("reconnect_failed", () => setStatus("status-disconnected", "Disconnected"));

    socket.on("sensor_data", function (d) {
        if (!d) return;
        local.lastSnap = d;
        local.packetCount += 1;

        const ax = num(d.ax, 0), ay = num(d.ay, 0), az = num(d.az, 0);
        updateAxisValue(el.valX, ax);
        updateAxisValue(el.valY, ay);
        updateAxisValue(el.valZ, az);
        updatePeaks(ax, ay, az);
        updateSparkline(ax);
        const tiltX = num(d.tilt_x, 0);
        const tiltY = num(d.tilt_y, 0);
        const tiltMag = num(d.tilt_magnitude, Math.hypot(tiltX, tiltY));
        if (el.valTilt) el.valTilt.textContent = tiltMag.toFixed(2);

        const alertDeg = num(d.tilt_limit_alert_deg, radToDeg(Math.atan(1 / 500)));
        const severeDeg = num(d.tilt_limit_severe_deg, radToDeg(Math.atan(1 / 300)));
        const criticalDeg = num(d.tilt_limit_critical_deg, radToDeg(Math.atan(1 / 200)));
        updateTiltGauge(tiltMag, alertDeg, severeDeg, criticalDeg);

        if (el.swayVelX) el.swayVelX.textContent = num(d.sway_velocity_x, 0).toFixed(4);
        if (el.swayVelY) el.swayVelY.textContent = num(d.sway_velocity_y, 0).toFixed(4);

        const torsion = num(d.torsion_angle, 0);
        if (el.torsion) {
            el.torsion.textContent = torsion.toFixed(2);
            el.torsion.className = "kv-value " + (Math.abs(torsion) > 5 ? "text-critical" : (Math.abs(torsion) > 2 ? "text-warning" : "text-safe"));
        }

        const dom = num(d.dominant_frequency, 0);
        const base = num(d.baseline_frequency_hz, 0);
        const shift = num(d.freq_shift_pct, 0);
        if (el.domFreq) el.domFreq.textContent = dom.toFixed(3);
        updateFreqHealth(dom, base, shift);

        if (typeof d.active_material === "string") {
            if (el.headerMaterial) el.headerMaterial.textContent = d.active_material;
            if (el.selMaterial && el.selMaterial.value !== d.active_material) {
                el.selMaterial.value = d.active_material;
            }
            local.lastMaterial = d.active_material;
        }
        if (typeof d.structural_system === "string") {
            local.lastStructural = d.structural_system;
        }
        updateWeightsNote();

        if (el.yieldVal) el.yieldVal.textContent = num(d.yield_strength, 0).toFixed(1);
        if (el.emod) el.emod.textContent = num(d.elastic_modulus, 0).toFixed(1);
        if (el.fatigue) el.fatigue.textContent = num(d.fatigue_limit, 0).toFixed(1);
        if (el.damping) el.damping.textContent = num(d.damping_ratio, 0).toFixed(3);

        const pS = num(d.penalty_stress, 0);
        const pF = num(d.penalty_fatigue, 0);
        const pFr = num(d.penalty_freq, 0);
        const pT = num(d.penalty_tilt, 0);
        const pD = num(d.penalty_disp, 0);
        updateWeightsPanel(pS, pF, pFr, pT, pD);

        if (displayState.scenarioActive) return;

        const disp = num(d.lateral_displacement, 0);
        if (el.disp) {
            el.disp.textContent = disp.toFixed(1);
            el.disp.className = "kv-value " + (disp > 10 ? "text-critical" : (disp > 5 ? "text-warning" : "text-safe"));
        }

        if (el.bend) el.bend.textContent = num(d.bending_stress, 0).toFixed(2);
        if (el.shear) el.shear.textContent = num(d.shear_stress, 0).toFixed(2);
        const ratio = num(d.stress_ratio, 0);
        if (el.bend) el.bend.className = "kv-value " + (ratio > 0.75 ? "text-critical" : (ratio > 0.5 ? "text-warning" : "text-safe"));
        if (el.shear) el.shear.className = "kv-value " + (ratio > 0.75 ? "text-critical" : (ratio > 0.5 ? "text-warning" : "text-safe"));

        if (el.stressRatio) el.stressRatio.textContent = Math.round(ratio * 100) + "%";
        if (el.barStressRatio) {
            el.barStressRatio.style.width = Math.round(ratio * 100) + "%";
            let color = "var(--ok)";
            if (ratio > 0.75) color = "var(--danger)";
            else if (ratio > 0.5) color = "var(--warning)";
            else if (ratio > 0.3) color = "var(--accent)";
            el.barStressRatio.style.background = color;
        }
        if (el.damage) el.damage.textContent = num(d.damage_percent, 0).toFixed(3);
        if (el.cycles) el.cycles.textContent = String(num(d.fatigue_cycles, 0) | 0);

        const score = num(d.integrity_score, 100);
        const tier = typeof d.alert_tier === "string" ? d.alert_tier : tierFromScore(score);
        if (el.integrity) el.integrity.textContent = Math.round(score);
        if (el.tier) {
            el.tier.textContent = tier;
            el.tier.style.color = tierColor(tier);
        }
        applyTierBadge(el.headerTier, tier);
        updateGauge(score, tier);

        const res = !!d.resonance_warning;
        if (el.resonance) el.resonance.textContent = res ? "YES" : "no";
        if (el.resonanceBadge) {
            el.resonanceBadge.textContent = res ? "Resonance ALERT" : "Resonance OK";
            el.resonanceBadge.classList.toggle("active", res);
        }
        if (el.evac) el.evac.textContent = d.evacuation_flag ? "YES" : "no";
        if (el.ttf) {
            const t = d.time_to_failure_hours;
            if (t === null || t === undefined || !isFinite(t) || t >= 9999) {
                el.ttf.innerHTML = "&infin;";
                if (el.ttfHuman) el.ttfHuman.textContent = "Safe baseline";
            } else {
                el.ttf.textContent = t.toFixed(1);
                if (el.ttfHuman) {
                    const days = Math.floor(t / 24);
                    const hours = Math.round(t % 24);
                    if (days > 0) el.ttfHuman.textContent = "~" + days + " days, " + hours + " hrs";
                    else el.ttfHuman.textContent = "~" + hours + " hrs remaining";
                }
            }
        }

        if (typeof d.scenario_active === "string") {
            if (el.scenarioName) el.scenarioName.textContent = d.scenario_active;
        }
        if (el.projStress) el.projStress.textContent = num(d.projected_stress, 0).toFixed(2);

        displayState.tiltX = tiltX;
        displayState.tiltY = tiltY;
        displayState.swayMag = Math.hypot(num(d.sway_velocity_x, 0), num(d.sway_velocity_y, 0));
        displayState.integrity = num(d.integrity_score, 100);
        displayState.damage = num(d.damage_percent, 0);
        displayState.tier = typeof d.alert_tier === "string" ? d.alert_tier : tierFromScore(displayState.integrity);
    });

    const displayState = {
        tiltX: 0, tiltY: 0, swayMag: 0,
        integrity: 100, damage: 0, tier: "nominal",
        scenarioActive: false,
    };

    const twin3d = (function initThreeD() {
        const mount = document.getElementById("twin3d-canvas-wrap");
        const loadingEl = document.getElementById("twin3d-loading");
        if (!mount || !window.THREE) {
            if (loadingEl) loadingEl.textContent = "Three.js unavailable";
            return null;
        }

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0a0c11);

        const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
        camera.position.set(12, 10, 16);

        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setPixelRatio(window.devicePixelRatio || 1);
        renderer.setSize(mount.clientWidth, mount.clientHeight);
        mount.appendChild(renderer.domElement);

        const ambient = new THREE.AmbientLight(0xffffff, 0.55);
        scene.add(ambient);
        const keyLight = new THREE.DirectionalLight(0xffffff, 0.95);
        keyLight.position.set(10, 20, 15);
        scene.add(keyLight);
        const fillLight = new THREE.DirectionalLight(0x4488ff, 0.25);
        fillLight.position.set(-10, 8, -8);
        scene.add(fillLight);

        const grid = new THREE.GridHelper(30, 30, 0x2a3045, 0x1a1f2e);
        grid.position.y = -0.01;
        scene.add(grid);

        const controls = (typeof THREE.OrbitControls === "function")
            ? new THREE.OrbitControls(camera, renderer.domElement)
            : null;
        if (controls) {
            controls.enableDamping = true;
            controls.dampingFactor = 0.08;
            controls.target.set(0, 3, 0);
            controls.update();
        }

        const buildingGroup = new THREE.Group();
        scene.add(buildingGroup);

        const material = new THREE.MeshStandardMaterial({
            color: 0x22c55e,
            emissive: 0x000000,
            emissiveIntensity: 0.0,
            roughness: 0.65,
            metalness: 0.15,
        });
        const geoCache = { originalPositions: null, mesh: null };

        function centerAndScale(obj) {
            const box = new THREE.Box3().setFromObject(obj);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());
            obj.position.sub(center);
            obj.position.y += size.y / 2;
            const maxDim = Math.max(size.x, size.y, size.z) || 1;
            const scale = 8 / maxDim;
            obj.scale.setScalar(scale);
        }

        const loader = new THREE.OBJLoader();
        loader.load(
            "/assets/cladire%20hack.obj",
            (obj) => {
                obj.traverse((c) => {
                    if (c.isMesh) {
                        c.material = material;
                        c.castShadow = true;
                        c.receiveShadow = true;
                        if (!geoCache.originalPositions && c.geometry && c.geometry.attributes.position) {
                            geoCache.originalPositions = c.geometry.attributes.position.array.slice(0);
                            geoCache.mesh = c;
                        }
                    }
                });
                centerAndScale(obj);
                buildingGroup.add(obj);
                if (loadingEl) loadingEl.classList.add("hidden");
            },
            undefined,
            (err) => {
                console.error("OBJ load failed:", err);
                if (loadingEl) loadingEl.textContent = "OBJ load failed - see console";
                const fallback = new THREE.Mesh(
                    new THREE.BoxGeometry(3, 7, 3),
                    material
                );
                fallback.position.y = 3.5;
                buildingGroup.add(fallback);
                geoCache.mesh = fallback;
                geoCache.originalPositions = fallback.geometry.attributes.position.array.slice(0);
            }
        );

        function resize() {
            const w = mount.clientWidth, h = mount.clientHeight;
            if (!w || !h) return;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h, false);
        }
        window.addEventListener("resize", resize);
        setTimeout(resize, 50);

        const TILT_AMP = 0.9;
        const SHEAR_MAX = 0.06;
        const SHAKE_MAX = 0.04;
        let smoothed = { tiltX: 0, tiltY: 0, integrity: 100, damage: 0 };

        function lerp(a, b, t) { return a + (b - a) * t; }

        function hexLerp(c1, c2, t) {
            const r1 = (c1 >> 16) & 0xff, g1 = (c1 >> 8) & 0xff, b1 = c1 & 0xff;
            const r2 = (c2 >> 16) & 0xff, g2 = (c2 >> 8) & 0xff, b2 = c2 & 0xff;
            const r = Math.round(lerp(r1, r2, t));
            const g = Math.round(lerp(g1, g2, t));
            const b = Math.round(lerp(b1, b2, t));
            return (r << 16) | (g << 8) | b;
        }

        function integrityColor(score) {
            if (score >= 50) {
                const t = (100 - score) / 50;
                return hexLerp(0x22c55e, 0xf59e0b, t);
            }
            const t = (50 - score) / 50;
            return hexLerp(0xf59e0b, 0xef4444, t);
        }

        let clock = new THREE.Clock();

        function applyShear(shearAmount) {
            if (!geoCache.mesh || !geoCache.originalPositions) return;
            const geom = geoCache.mesh.geometry;
            const pos = geom.attributes.position.array;
            const orig = geoCache.originalPositions;
            let minY = Infinity, maxY = -Infinity;
            for (let i = 1; i < orig.length; i += 3) {
                if (orig[i] < minY) minY = orig[i];
                if (orig[i] > maxY) maxY = orig[i];
            }
            const range = (maxY - minY) || 1;
            for (let i = 0; i < orig.length; i += 3) {
                const y = orig[i + 1];
                const t = (y - minY) / range;
                pos[i] = orig[i] + shearAmount * t;
                pos[i + 1] = y;
                pos[i + 2] = orig[i + 2];
            }
            geom.attributes.position.needsUpdate = true;
            geom.computeVertexNormals();
        }

        function render() {
            requestAnimationFrame(render);
            clock.getDelta();
            const now = clock.elapsedTime;

            smoothed.tiltX = lerp(smoothed.tiltX, displayState.tiltX, 0.06);
            smoothed.tiltY = lerp(smoothed.tiltY, displayState.tiltY, 0.06);
            smoothed.integrity = lerp(smoothed.integrity, displayState.integrity, 0.05);
            smoothed.damage = lerp(smoothed.damage, displayState.damage, 0.03);

            const tiltXRad = (smoothed.tiltY * Math.PI / 180) * TILT_AMP;
            const tiltZRad = -(smoothed.tiltX * Math.PI / 180) * TILT_AMP;
            buildingGroup.rotation.x = tiltXRad;
            buildingGroup.rotation.z = tiltZRad;

            const shakeScale = Math.min(1, displayState.swayMag * 1.2) * SHAKE_MAX;
            buildingGroup.position.x = (Math.random() - 0.5) * shakeScale;
            buildingGroup.position.z = (Math.random() - 0.5) * shakeScale;

            material.color.setHex(integrityColor(smoothed.integrity));

            const shear = Math.min(1, smoothed.damage / 80) * SHEAR_MAX;
            applyShear(shear);

            const tier = displayState.tier;
            if (tier === "critical" || tier === "evacuate") {
                const pulse = 0.15 + 0.2 * Math.sin(now * 4.0);
                material.emissive.setHex(tier === "evacuate" ? 0xef4444 : 0xfb923c);
                material.emissiveIntensity = pulse;
            } else {
                material.emissive.setHex(0x000000);
                material.emissiveIntensity = 0.0;
            }

            if (controls) controls.update();
            renderer.render(scene, camera);
        }
        render();

        return {
            setScenarioMode(active, kind) {
                const modeEl = document.getElementById("twin3d-mode");
                if (modeEl) {
                    modeEl.textContent = active ? ("SCENARIO: " + (kind || "").toUpperCase()) : "LIVE";
                    modeEl.classList.toggle("scenario", !!active);
                }
            },
        };
    })();

    const scenarioChart = (function initChart() {
        const canvas = document.getElementById("scenario-chart");
        if (!canvas || !window.Chart) return null;
        const ctx = canvas.getContext("2d");
        const chart = new Chart(ctx, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    { label: "Stress (MPa)", data: [], borderColor: "#f59e0b",
                      backgroundColor: "rgba(245,158,11,0.1)", borderWidth: 1.5,
                      yAxisID: "y", pointRadius: 0, tension: 0.25 },
                    { label: "Disp (mm)", data: [], borderColor: "#00d4ff",
                      backgroundColor: "rgba(0,212,255,0.1)", borderWidth: 1.5,
                      yAxisID: "y", pointRadius: 0, tension: 0.25 },
                    { label: "Integrity", data: [], borderColor: "#22c55e",
                      backgroundColor: "rgba(34,197,94,0.1)", borderWidth: 1.5,
                      yAxisID: "y1", pointRadius: 0, tension: 0.25 },
                ],
            },
            options: {
                animation: false, responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: "#e2e8f0", font: { size: 10 } } },
                    tooltip: { enabled: false },
                },
                scales: {
                    x: { ticks: { color: "#64748b", font: { size: 9 } },
                         grid: { color: "#2a3045" } },
                    y: { position: "left",
                         ticks: { color: "#f59e0b", font: { size: 9 } },
                         grid: { color: "#2a3045" } },
                    y1: { position: "right", min: 0, max: 100,
                          ticks: { color: "#22c55e", font: { size: 9 } },
                          grid: { drawOnChartArea: false } },
                },
            },
        });
        return {
            reset() {
                chart.data.labels = [];
                chart.data.datasets.forEach(ds => ds.data = []);
                chart.update("none");
            },
            push(t, stress, disp, integrity) {
                chart.data.labels.push(t.toFixed(1));
                chart.data.datasets[0].data.push(stress);
                chart.data.datasets[1].data.push(disp);
                chart.data.datasets[2].data.push(integrity);
                chart.update("none");
            },
        };
    })();

    const projStatusEl = document.getElementById("val-proj-status");

    socket.on("scenario_stream", function (d) {
        if (!d) return;
        if (d.phase === "start") {
            displayState.scenarioActive = true;
            if (twin3d) twin3d.setScenarioMode(true, d.scenario);
            if (scenarioChart) scenarioChart.reset();
            if (el.scenarioName) el.scenarioName.textContent = d.scenario_full || d.scenario;
            const tgt = num(d.target_stress_mpa, 0);
            const yld = num(d.yield_strength_mpa, 0);
            const ratioPct = num(d.target_ratio_pct, 0);
            if (el.projStress) el.projStress.textContent = tgt.toFixed(2);
            if (projStatusEl) {
                const status = d.safe ? "SAFE" : "EXCEEDS YIELD";
                const cls = d.safe ? "text-safe" : "text-critical";
                projStatusEl.textContent = ratioPct.toFixed(1) + "% of yield (" + yld.toFixed(0) + " MPa) — " + status;
                projStatusEl.className = "kv-value " + cls;
            }
            return;
        }
        if (d.phase === "frame") {
            const bend = num(d.bending_stress, 0);
            const shear = num(d.shear_stress, 0);
            const ratio = num(d.stress_ratio, 0);
            const dispF = num(d.lateral_displacement, 0);
            const dmg = num(d.damage_percent, 0);
            const score = num(d.integrity_score, displayState.integrity);
            const tier = typeof d.alert_tier === "string" ? d.alert_tier : tierFromScore(score);

            displayState.integrity = score;
            displayState.damage = dmg;
            displayState.tier = tier;
            displayState.swayMag = 0.02 + ratio * 0.25;
            displayState.tiltX = Math.sin(d.progress * Math.PI * 3) * 1.2 * ratio;
            displayState.tiltY = Math.cos(d.progress * Math.PI * 2.5) * 1.0 * ratio;

            const stressClass = "kv-value " + (ratio > 0.75 ? "text-critical" : (ratio > 0.5 ? "text-warning" : "text-safe"));
            if (el.bend) { el.bend.textContent = bend.toFixed(2); el.bend.className = stressClass; }
            if (el.shear) { el.shear.textContent = shear.toFixed(2); el.shear.className = stressClass; }
            if (el.stressRatio) el.stressRatio.textContent = Math.round(ratio * 100) + "%";
            if (el.barStressRatio) {
                el.barStressRatio.style.width = Math.round(ratio * 100) + "%";
                let color = "var(--ok)";
                if (ratio > 0.75) color = "var(--danger)";
                else if (ratio > 0.5) color = "var(--warning)";
                else if (ratio > 0.3) color = "var(--accent)";
                el.barStressRatio.style.background = color;
            }
            if (el.damage) el.damage.textContent = dmg.toFixed(3);
            if (el.disp) {
                el.disp.textContent = dispF.toFixed(1);
                el.disp.className = "kv-value " + (dispF > 10 ? "text-critical" : (dispF > 5 ? "text-warning" : "text-safe"));
            }

            const stepEl = document.getElementById("val-scenario-step");
            if (stepEl) stepEl.textContent = d.step + "/" + d.n_steps;

            if (el.integrity) el.integrity.textContent = Math.round(score);
            if (el.tier) {
                el.tier.textContent = tier;
                el.tier.style.color = tierColor(tier);
            }
            applyTierBadge(el.headerTier, tier);
            updateGauge(score, tier);

            if (el.evac) el.evac.textContent = (tier === "evacuate") ? "YES" : "no";
            if (el.ttf) {
                el.ttf.textContent = "—";
                if (el.ttfHuman) el.ttfHuman.textContent = "Simulated scenario";
            }
            if (el.resonance) el.resonance.textContent = "sim";
            if (el.resonanceBadge) {
                el.resonanceBadge.textContent = "Scenario run";
                el.resonanceBadge.classList.remove("active");
            }

            if (scenarioChart) scenarioChart.push(d.t_s, bend, dispF, score);
            return;
        }
        if (d.phase === "end" || d.phase === "error") {
            displayState.scenarioActive = false;
            if (twin3d) twin3d.setScenarioMode(false);
            scenarioBtns.forEach(b => b.classList.remove("active"));
            if (el.scenarioName) el.scenarioName.textContent = "none";
            if (el.projStress) el.projStress.textContent = "0.00";
            if (projStatusEl) {
                projStatusEl.textContent = "—";
                projStatusEl.className = "kv-value";
            }
        }
    });
})();
