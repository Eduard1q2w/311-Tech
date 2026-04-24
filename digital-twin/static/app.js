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

        if (!displayState.scenarioActive) {
            displayState.tiltX = num(d.tilt_x, 0);
            displayState.tiltY = num(d.tilt_y, 0);
            displayState.swayMag = Math.hypot(num(d.sway_velocity_x, 0), num(d.sway_velocity_y, 0));
            displayState.integrity = num(d.integrity_score, 100);
            displayState.damage = num(d.damage_percent, 0);
            displayState.tier = typeof d.alert_tier === "string" ? d.alert_tier : tierFromScore(displayState.integrity);
        }
    });

    const displayState = {
        tiltX: 0, tiltY: 0, swayMag: 0,
        integrity: 100, damage: 0, tier: "nominal",
        scenarioActive: false,
    };

    const twin3d = (function initThreeD() {
        const mount = document.getElementById("twin3d-canvas-wrap");
        const loadingEl = document.getElementById("twin3d-loading");
        const spriteEl = document.getElementById("twin3d-sprite");
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
                if (loadingEl) loadingEl.textContent = "OBJ load failed — see console";
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

        const TILT_AMP = 3.0;
        const SHEAR_MAX = 0.25;
        const SHAKE_MAX = 0.15;
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
            const dt = clock.getDelta();
            const now = clock.elapsedTime;

            smoothed.tiltX = lerp(smoothed.tiltX, displayState.tiltX, 0.12);
            smoothed.tiltY = lerp(smoothed.tiltY, displayState.tiltY, 0.12);
            smoothed.integrity = lerp(smoothed.integrity, displayState.integrity, 0.08);
            smoothed.damage = lerp(smoothed.damage, displayState.damage, 0.04);

            const tiltXRad = (smoothed.tiltY * Math.PI / 180) * TILT_AMP;
            const tiltZRad = -(smoothed.tiltX * Math.PI / 180) * TILT_AMP;
            buildingGroup.rotation.x = tiltXRad;
            buildingGroup.rotation.z = tiltZRad;

            const shakeScale = Math.min(1, displayState.swayMag * 2.0) * SHAKE_MAX;
            buildingGroup.position.x = (Math.random() - 0.5) * shakeScale;
            buildingGroup.position.z = (Math.random() - 0.5) * shakeScale;

            material.color.setHex(integrityColor(smoothed.integrity));

            const shear = Math.min(1, smoothed.damage / 50) * SHEAR_MAX;
            applyShear(shear);

            const tier = displayState.tier;
            if (tier === "critical" || tier === "evacuate") {
                const pulse = 0.4 + 0.4 * Math.sin(now * 6.0);
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

        const SPRITE_MAP = {
            wind:     { folder: "tilt_front", n: 10 },
            seismic:  { folder: "tilt_left",  n: 10 },
            overload: { folder: "tilt_back",  n: 10 },
            thermal:  { folder: "tilt_right", n: 10 },
            flood:    { folder: "tilt_front", n: 10 },
        };
        let spriteTimer = null;
        function startSprite(kind) {
            stopSprite();
            const cfg = SPRITE_MAP[kind];
            if (!cfg || !spriteEl) return;
            let i = 1;
            const tick = () => {
                const idx = String(i).padStart(4, "0");
                spriteEl.style.backgroundImage =
                    `url('/assets/${cfg.folder}/${idx}.png')`;
                spriteEl.classList.add("visible");
                i = (i % cfg.n) + 1;
            };
            tick();
            spriteTimer = setInterval(tick, 120);
        }
        function stopSprite() {
            if (spriteTimer) { clearInterval(spriteTimer); spriteTimer = null; }
            if (spriteEl) { spriteEl.classList.remove("visible"); spriteEl.style.backgroundImage = ""; }
        }

        return {
            setScenarioMode(active, kind) {
                const modeEl = document.getElementById("twin3d-mode");
                if (modeEl) {
                    modeEl.textContent = active ? ("SCENARIO: " + (kind || "").toUpperCase()) : "LIVE";
                    modeEl.classList.toggle("scenario", !!active);
                }
                if (active) startSprite(kind);
                else stopSprite();
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

    socket.on("scenario_stream", function (d) {
        if (!d) return;
        if (d.phase === "start") {
            displayState.scenarioActive = true;
            if (twin3d) twin3d.setScenarioMode(true, d.scenario);
            if (scenarioChart) scenarioChart.reset();
            if (el.scenarioName) el.scenarioName.textContent = d.scenario_full || d.scenario;
            return;
        }
        if (d.phase === "frame") {
            displayState.integrity = num(d.integrity_score, displayState.integrity);
            displayState.damage = num(d.damage_percent, displayState.damage);
            displayState.tier = typeof d.alert_tier === "string" ? d.alert_tier : displayState.tier;
            const ratio = num(d.stress_ratio, 0);
            displayState.swayMag = 0.05 + ratio * 0.6;
            displayState.tiltX = Math.sin(d.progress * Math.PI * 4) * 3.0 * ratio;
            displayState.tiltY = Math.cos(d.progress * Math.PI * 3) * 3.0 * ratio;

            if (el.projStress) el.projStress.textContent = num(d.bending_stress, 0).toFixed(2);
            const stepEl = document.getElementById("val-scenario-step");
            if (stepEl) stepEl.textContent = d.step + "/" + d.n_steps;

            if (el.integrity) el.integrity.textContent = Math.round(displayState.integrity);
            if (el.tier) {
                el.tier.textContent = displayState.tier;
                el.tier.style.color = tierColor(displayState.tier);
            }
            applyTierBadge(el.headerTier, displayState.tier);
            updateGauge(displayState.integrity, displayState.tier);

            if (scenarioChart) scenarioChart.push(
                d.t_s,
                num(d.bending_stress, 0),
                num(d.lateral_displacement, 0),
                num(d.integrity_score, 0)
            );
            return;
        }
        if (d.phase === "end" || d.phase === "error") {
            displayState.scenarioActive = false;
            if (twin3d) twin3d.setScenarioMode(false);
            scenarioBtns.forEach(b => b.classList.remove("active"));
            if (el.scenarioName) el.scenarioName.textContent = "none";
        }
    });
})();
