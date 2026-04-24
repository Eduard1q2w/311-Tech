import eventlet
eventlet.monkey_patch()

import os
import socket

from twin_state import state
import sensor_reader
import sensor_processor
import material_db
import stress_model
import scenario_engine
import scenario_stream
import predictor

ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "3ddio")
)

try:
    import mechanics_engine
    _has_mechanics = True
except ImportError as e:
    print(f"[server] mechanics_engine not available: {type(e).__name__}: {e}")
    _has_mechanics = False


def _start_all_layers():
    print("=" * 60)
    print(" Durian — booting engineering stack")
    print("=" * 60)
    print("  [1/8] twin_state ........... loaded")
    print("  [2/8] sensor_reader ........ loaded (thread auto-started)")
    sensor_processor.start()
    print("  [3/8] sensor_processor ..... started")
    if _has_mechanics:
        mechanics_engine.start()
        print("  [4/8] mechanics_engine ..... started")
    else:
        print("  [4/8] mechanics_engine ..... not found (skipped)")
    material_db.set_active("reinforced_concrete")
    print("  [5/8] material_db .......... loaded (active: reinforced_concrete)")
    stress_model.start()
    print("  [6/8] stress_model ......... started")
    print("  [7/8] scenario_engine ...... loaded (on-demand)")
    predictor.start()
    print("  [8/8] predictor ............ started")
    print("-" * 60)


_start_all_layers()

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_socketio import SocketIO

app = Flask(__name__)
app.config["SECRET_KEY"] = "durian-dev"
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

BROADCAST_INTERVAL = 0.05


def _get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def _broadcast_loop():
    while not sensor_reader.stop_event.is_set():
        try:
            payload = state.to_dict()
            socketio.emit("sensor_data", payload)
        except Exception as e:
            print(f"[broadcast] error: {type(e).__name__}: {e}")
        socketio.sleep(BROADCAST_INTERVAL)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    return jsonify(state.to_dict())


@app.route("/api/material", methods=["POST"])
def api_set_material():
    body = request.get_json(force=True)
    name = body.get("material", "")
    try:
        material_db.set_active(name)
        mat = material_db.get_active()
        return jsonify({"status": "ok", "active_material": mat.name})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/scenario", methods=["POST"])
def api_set_scenario():
    body = request.get_json(force=True)
    name = body.pop("scenario", "")
    try:
        result = scenario_engine.set_active_scenario(name, **body)
        return jsonify({"status": "ok", "result": result.to_dict()})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/scenario", methods=["DELETE"])
def api_clear_scenario():
    scenario_engine.clear_scenario()
    return jsonify({"status": "ok", "scenario_active": "none"})


@app.route("/api/scenario/all")
def api_all_scenarios():
    results = scenario_engine.run_all_scenarios()
    return jsonify({name: r.to_dict() for name, r in results.items()})


@app.route("/api/calibrate", methods=["POST"])
def api_calibrate():
    result = sensor_processor.recalibrate()
    stress_model.reset_damage()
    predictor.reset_baseline()
    if _has_mechanics:
        mechanics_engine.reset()
    return jsonify({"status": "ok", "calibration": result})


@app.route("/api/reset_damage", methods=["POST"])
def api_reset_damage():
    stress_model.reset_damage()
    predictor.reset_baseline()
    return jsonify({"status": "ok", "damage_percent": 0.0, "integrity_score": 100.0})


@app.route("/assets/<path:subpath>")
def api_assets(subpath):
    return send_from_directory(ASSETS_DIR, subpath)


@app.route("/run_scenario", methods=["POST"])
def api_run_scenario():
    body = request.get_json(force=True) or {}
    kind = body.get("scenario", "")
    intensity = body.get("intensity", 0.5)
    try:
        info = scenario_stream.start_scenario(socketio, kind, float(intensity))
        return jsonify(info)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/stop_scenario", methods=["POST"])
def api_stop_scenario():
    return jsonify(scenario_stream.stop_scenario())


@app.route("/api/dimensions", methods=["POST"])
def api_set_dimensions():
    body = request.get_json(force=True)
    h = float(body.get("height", 10.0))
    w = float(body.get("width", 0.3))
    d = float(body.get("depth", 0.3))
    m = float(body.get("mass", 5000.0))
    stories = body.get("stories", None)
    floor_height = body.get("floor_height", None)
    plan_width = body.get("plan_width", w)
    plan_depth = body.get("plan_depth", d)
    structural_system = body.get("structural_system", None)
    stress_model.set_dimensions(
        h, w, d, m,
        stories=int(stories) if stories is not None else None,
        floor_height=float(floor_height) if floor_height is not None else None,
        plan_width=float(plan_width) if plan_width is not None else None,
        plan_depth=float(plan_depth) if plan_depth is not None else None,
        structural_system=structural_system,
    )
    return jsonify({
        "status": "ok",
        "dimensions": {
            "height_m": h, "width_m": w, "depth_m": d, "mass_kg": m,
            "stories": stories, "floor_height": floor_height,
            "plan_width": plan_width, "plan_depth": plan_depth,
            "structural_system": structural_system,
        }
    })


@socketio.on("connect")
def _on_connect():
    socketio.emit("sensor_data", state.to_dict())


if __name__ == "__main__":
    ip = _get_local_ip()
    mat = material_db.get_active()
    print(f"  Active material : {mat.name}")
    print(f"  Yield strength  : {mat.yield_strength} MPa")
    print(f"  Elastic modulus : {mat.elastic_modulus} GPa")
    print("-" * 60)
    print(f"  Local:   http://127.0.0.1:5000")
    print(f"  Network: http://{ip}:5000")
    print("=" * 60)

    socketio.start_background_task(_broadcast_loop)

    try:
        socketio.run(app, host="0.0.0.0", port=5000)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        sensor_reader.stop_event.set()
        stress_model.stop()
        predictor.stop()
        sensor_processor.stop()
        if _has_mechanics:
            mechanics_engine.stop()
        try:
            sensor_reader.sensor_thread.join(timeout=1.0)
        except Exception:
            pass
