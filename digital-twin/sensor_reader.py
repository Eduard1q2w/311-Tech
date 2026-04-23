import smbus2
import threading
import queue
import time

I2C_BUS = 1
MPU6050_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B
ACCEL_SCALE = 16384.0
POLL_INTERVAL = 0.05

data_queue = queue.Queue(maxsize=5)
stop_event = threading.Event()


def _to_signed(value):
    if value >= 0x8000:
        return value - 0x10000
    return value


def _poll_loop():
    bus = smbus2.SMBus(I2C_BUS)
    try:
        bus.write_byte_data(MPU6050_ADDR, PWR_MGMT_1, 0x00)
        time.sleep(0.1)
        while not stop_event.is_set():
            try:
                block = bus.read_i2c_block_data(MPU6050_ADDR, ACCEL_XOUT_H, 6)
                x_raw = _to_signed((block[0] << 8) | block[1])
                y_raw = _to_signed((block[2] << 8) | block[3])
                z_raw = _to_signed((block[4] << 8) | block[5])
                reading = {
                    "x": round(x_raw / ACCEL_SCALE, 4),
                    "y": round(y_raw / ACCEL_SCALE, 4),
                    "z": round(z_raw / ACCEL_SCALE, 4),
                    "t": round(time.time(), 4),
                }
                try:
                    data_queue.put_nowait(reading)
                except queue.Full:
                    pass
            except OSError:
                pass
            time.sleep(POLL_INTERVAL)
    finally:
        try:
            bus.close()
        except Exception:
            pass


sensor_thread = threading.Thread(target=_poll_loop, name="MPU6050Poller", daemon=True)
sensor_thread.start()


if __name__ == "__main__":
    try:
        while True:
            reading = data_queue.get()
            print(
                "X: {x:+.4f} g   Y: {y:+.4f} g   Z: {z:+.4f} g   t={t:.4f}".format(**reading)
            )
    except KeyboardInterrupt:
        stop_event.set()
        sensor_thread.join(timeout=1.0)
