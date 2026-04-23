(function () {
    "use strict";

    const SWAY_WINDOW = 20;
    const SWAY_RANGE = 1.0;
    const SIGNIFICANT_THRESHOLD = 0.3;
    const RATE_INTERVAL_MS = 1000;

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
    };

    const state = {
        peaks: { x: 0, y: 0, z: 0 },
        swayBuffer: [],
        packetCount: 0,
        connected: false,
    };

    function setStatus(cls, text) {
        if (!el.statusDot || !el.statusText) return;
        el.statusDot.classList.remove(
            "status-connected",
            "status-disconnected",
            "status-warning"
        );
        el.statusDot.classList.add(cls);
        el.statusText.textContent = text;
    }

    function formatSigned(value, decimals) {
        const sign = value >= 0 ? "+" : "";
        return sign + value.toFixed(decimals);
    }

    function updateAxisValue(element, value) {
        if (!element) return;
        element.textContent = formatSigned(value, 2);
        if (Math.abs(value) > SIGNIFICANT_THRESHOLD) {
            element.style.color = "var(--danger)";
        } else {
            element.style.color = "var(--accent)";
        }
    }

    function updatePeaks(x, y, z) {
        const ax = Math.abs(x);
        const ay = Math.abs(y);
        const az = Math.abs(z);
        if (ax > state.peaks.x) state.peaks.x = ax;
        if (ay > state.peaks.y) state.peaks.y = ay;
        if (az > state.peaks.z) state.peaks.z = az;
        if (el.peakX) el.peakX.textContent = state.peaks.x.toFixed(2);
        if (el.peakY) el.peakY.textContent = state.peaks.y.toFixed(2);
        if (el.peakZ) el.peakZ.textContent = state.peaks.z.toFixed(2);
    }

    function resetPeaks() {
        state.peaks.x = 0;
        state.peaks.y = 0;
        state.peaks.z = 0;
        if (el.peakX) el.peakX.textContent = "0.00";
        if (el.peakY) el.peakY.textContent = "0.00";
        if (el.peakZ) el.peakZ.textContent = "0.00";
    }

    function updateTilt(y, z) {
        if (!el.valTilt) return;
        const angle = Math.atan2(y, z) * (180 / Math.PI);
        el.valTilt.textContent = angle.toFixed(1);
    }

    function updateSparkline(xValue) {
        if (!el.sparkline) return;
        state.swayBuffer.push(xValue);
        if (state.swayBuffer.length > SWAY_WINDOW) {
            state.swayBuffer.shift();
        }
        const W = 200;
        const H = 48;
        const mid = H / 2;
        const count = state.swayBuffer.length;
        if (count < 2) {
            el.sparkline.innerHTML = "";
            return;
        }
        const step = W / (SWAY_WINDOW - 1);
        const points = state.swayBuffer
            .map(function (v, i) {
                const clamped = Math.max(-SWAY_RANGE, Math.min(SWAY_RANGE, v));
                const px = i * step;
                const py = mid - (clamped / SWAY_RANGE) * (H / 2);
                return px.toFixed(2) + "," + py.toFixed(2);
            })
            .join(" ");
        el.sparkline.innerHTML =
            '<svg viewBox="0 0 ' + W + ' ' + H + '" ' +
            'preserveAspectRatio="none" ' +
            'xmlns="http://www.w3.org/2000/svg">' +
            '<polyline points="' + points + '" ' +
            'fill="none" stroke="#00d4ff" stroke-width="1.5" ' +
            'vector-effect="non-scaling-stroke"/>' +
            '</svg>';
    }

    function tickSampleRate() {
        if (el.valHz) {
            el.valHz.textContent = String(state.packetCount);
        }
        state.packetCount = 0;
    }

    setInterval(tickSampleRate, RATE_INTERVAL_MS);

    if (el.resetPeaks) {
        el.resetPeaks.addEventListener("click", resetPeaks);
    }

    setStatus("status-disconnected", "Disconnected");

    const socket = io({
        reconnection: true,
        reconnectionDelay: 2000,
        reconnectionDelayMax: 2000,
        reconnectionAttempts: Infinity,
        transports: ["websocket", "polling"],
    });

    socket.on("connect", function () {
        state.connected = true;
        setStatus("status-connected", "Live");
    });

    socket.on("disconnect", function () {
        state.connected = false;
        setStatus("status-disconnected", "Disconnected");
    });

    socket.io.on("reconnect_attempt", function () {
        if (!state.connected) {
            setStatus("status-warning", "Reconnecting...");
        }
    });

    socket.io.on("reconnect_error", function () {
        if (!state.connected) {
            setStatus("status-warning", "Reconnecting...");
        }
    });

    socket.io.on("reconnect_failed", function () {
        setStatus("status-disconnected", "Disconnected");
    });

    socket.on("sensor_data", function (data) {
        if (!data || typeof data.x !== "number") return;
        state.packetCount += 1;
        updateAxisValue(el.valX, data.x);
        updateAxisValue(el.valY, data.y);
        updateAxisValue(el.valZ, data.z);
        updatePeaks(data.x, data.y, data.z);
        updateTilt(data.y, data.z);
        updateSparkline(data.x);
    });
})();
