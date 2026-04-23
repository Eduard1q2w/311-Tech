import eventlet
eventlet.monkey_patch()

import socket
import threading
import time
import queue as _queue

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO

import sensor_reader

app = Flask(__name__)
app.config["SECRET_KEY"] = "digital-twin-dev"
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

_latest_lock = threading.Lock()
_latest_reading = {"x": 0.0, "y": 0.0, "z": 0.0, "timestamp": 0}


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
    global _latest_reading
    while not sensor_reader.stop_event.is_set():
        try:
            reading = sensor_reader.data_queue.get(timeout=0.5)
        except _queue.Empty:
            socketio.sleep(0)
            continue
        payload = {
            "x": reading["x"],
            "y": reading["y"],
            "z": reading["z"],
            "timestamp": int(time.time() * 1000),
        }
        with _latest_lock:
            _latest_reading = payload
        socketio.emit("sensor_data", payload)
        socketio.sleep(0)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    with _latest_lock:
        snapshot = dict(_latest_reading)
    return jsonify(snapshot)


@socketio.on("connect")
def _on_connect():
    with _latest_lock:
        snapshot = dict(_latest_reading)
    socketio.emit("sensor_data", snapshot)


if __name__ == "__main__":
    ip = _get_local_ip()
    print("=" * 60)
    print(" Predictive Digital Twin server")
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
        try:
            sensor_reader.sensor_thread.join(timeout=1.0)
        except Exception:
            pass
