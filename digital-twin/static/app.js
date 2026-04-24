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

        forecast: document.getElementById("forecast-container"),

        scenarioName: document.getElementById("val-scenario"),
        projStress: document.getElementById("val-proj-stress"),
        btnClearScenario: document.getElementById("btn-clear-scenario"),

        btnCalibrate: document.getElementById("btn-calibrate"),

        btnSyncBuilding: document.getElementById("btn-sync-building"),
        inBHeight: document.getElementById("in-b-height"),
        inBMass: document.getElementById("in-b-mass"),
        inBWidth: document.getElementById("in-b-width"),
        inBDepth: document.getElementById("in-b-depth"),
        ttfHuman: document.getElementById("val-ttf-human"),
    };

    const local = {
        peaks: { x: 0, y: 0, z: 0 },
        swayBuffer: [],
        packetCount: 0,
        connected: false,
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

    function updateForecast(points) {
        if (!el.forecast || !Array.isArray(points) || points.length < 2) return;
        const W = 400, H = 120, pad = 4;
        const maxVal = 100, minVal = 0;
        const n = points.length;
        const step = (W - pad * 2) / (n - 1);
        const toY = v => pad + (1 - (v - minVal) / (maxVal - minVal)) * (H - pad * 2);
        const coords = points.map((v, i) => (pad + i * step).toFixed(1) + "," + toY(v).toFixed(1));
        const strokeColor = tierColor(tierFromScore(points[0]));
        const grid = [25, 50, 75].map(g => {
            const y = toY(g).toFixed(1);
            return '<line x1="' + pad + '" y1="' + y + '" x2="' + (W - pad) + '" y2="' + y +
                '" stroke="#2a3045" stroke-width="0.5" stroke-dasharray="2 3"/>';
        }).join("");
        const area = "M" + coords[0] + " L" + coords.slice(1).join(" L") +
            " L" + (W - pad) + "," + (H - pad) + " L" + pad + "," + (H - pad) + " Z";
        el.forecast.innerHTML =
            '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">' +
            grid +
            '<path d="' + area + '" fill="' + strokeColor + '" fill-opacity="0.12"/>' +
            '<polyline points="' + coords.join(" ") + '" fill="none" stroke="' + strokeColor +
            '" stroke-width="1.8" vector-effect="non-scaling-stroke"/>' +
            '</svg>';
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

    function apiDelete(url) {
        return fetch(url, { method: "DELETE" }).then(r => r.json());
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

    if (el.btnClearScenario) {
        el.btnClearScenario.addEventListener("click", () => {
            apiDelete("/api/scenario").catch(console.error);
        });
    }

    document.querySelectorAll("[data-scenario]").forEach(btn => {
        btn.addEventListener("click", () => {
            const kind = btn.getAttribute("data-scenario");
            let body = {};
            if (kind === "wind") {
                body = { scenario: "wind_load", wind_speed_kmh: parseFloat(document.getElementById("in-wind").value) };
            } else if (kind === "seismic") {
                body = { scenario: "seismic_load",
                    magnitude: parseFloat(document.getElementById("in-mag").value),
                    distance_km: parseFloat(document.getElementById("in-dist").value) };
            } else if (kind === "overload") {
                body = { scenario: "overload",
                    extra_floors: parseInt(document.getElementById("in-floors").value, 10),
                    occupancy_pct: parseFloat(document.getElementById("in-occ").value) };
            } else if (kind === "thermal") {
                body = { scenario: "thermal_stress",
                    delta_temp_c: parseFloat(document.getElementById("in-temp").value) };
            } else if (kind === "flood") {
                body = { scenario: "flood_hydrostatic",
                    water_depth_m: parseFloat(document.getElementById("in-depth").value) };
            }
            apiPost("/api/scenario", body).catch(console.error);
        });
    });

    if (el.btnSyncBuilding) {
        el.btnSyncBuilding.addEventListener("click", () => {
            const body = {
                height: parseFloat(el.inBHeight.value),
                mass: parseFloat(el.inBMass.value),
                width: parseFloat(el.inBWidth.value),
                depth: parseFloat(el.inBDepth.value)
            };
            apiPost("/api/dimensions", body).then(res => {
                if (res.status === "ok") {
                    el.btnSyncBuilding.textContent = "Synced!";
                    setTimeout(() => el.btnSyncBuilding.textContent = "Sync to Twin", 2000);
                }
            }).catch(console.error);
        });
    }

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
        local.packetCount += 1;

        const ax = num(d.ax, 0), ay = num(d.ay, 0), az = num(d.az, 0);
        updateAxisValue(el.valX, ax);
        updateAxisValue(el.valY, ay);
        updateAxisValue(el.valZ, az);
        updatePeaks(ax, ay, az);
        updateSparkline(ax);
        if (el.valTilt) el.valTilt.textContent = num(d.tilt_x, 0).toFixed(1);

        if (el.swayVelX) el.swayVelX.textContent = num(d.sway_velocity_x, 0).toFixed(4);
        if (el.swayVelY) el.swayVelY.textContent = num(d.sway_velocity_y, 0).toFixed(4);
        
        const disp = num(d.lateral_displacement, 0);
        if (el.disp) {
            el.disp.textContent = disp.toFixed(1);
            el.disp.className = "kv-value " + (disp > 10 ? "text-critical" : (disp > 5 ? "text-warning" : "text-safe"));
        }
        
        const torsion = num(d.torsion_angle, 0);
        if (el.torsion) {
            el.torsion.textContent = torsion.toFixed(2);
            el.torsion.className = "kv-value " + (Math.abs(torsion) > 5 ? "text-critical" : (Math.abs(torsion) > 2 ? "text-warning" : "text-safe"));
        }
        
        if (el.domFreq) el.domFreq.textContent = num(d.dominant_frequency, 0).toFixed(3);

        if (typeof d.active_material === "string") {
            if (el.headerMaterial) el.headerMaterial.textContent = d.active_material;
            if (el.selMaterial && el.selMaterial.value !== d.active_material) {
                el.selMaterial.value = d.active_material;
            }
        }
        if (el.yieldVal) el.yieldVal.textContent = num(d.yield_strength, 0).toFixed(1);
        if (el.emod) el.emod.textContent = num(d.elastic_modulus, 0).toFixed(1);
        if (el.fatigue) el.fatigue.textContent = num(d.fatigue_limit, 0).toFixed(1);
        if (el.damping) el.damping.textContent = num(d.damping_ratio, 0).toFixed(3);

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
                    if (days > 0) el.ttfHuman.textContent = `~${days} days, ${hours} hrs`;
                    else el.ttfHuman.textContent = `~${hours} hrs remaining`;
                }
            }
        }

        if (Array.isArray(d.forecast_24h)) updateForecast(d.forecast_24h);

        if (typeof d.scenario_active === "string") {
            if (el.scenarioName) el.scenarioName.textContent = d.scenario_active;
        }
        if (el.projStress) el.projStress.textContent = num(d.projected_stress, 0).toFixed(2);
    });
})();
