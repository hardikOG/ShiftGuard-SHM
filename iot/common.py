"""Shared MQTT settings and helpers for the live AIoT pipeline."""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_BROKER = os.environ.get("SHM_BROKER", "localhost")
DEFAULT_PORT = int(os.environ.get("SHM_PORT", "1883"))
DEFAULT_WS_PORT = int(os.environ.get("SHM_WS_PORT", "9001"))
BRIDGE_ID = os.environ.get("SHM_BRIDGE", "bridge01")


def topic(*parts, bridge=BRIDGE_ID):
    return "/".join(["shm", bridge, *[str(p) for p in parts]])


def make_client(client_id):
    import paho.mqtt.client as mqtt
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:            # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"))


def port_open(host, port, timeout=0.5):
    """True if something accepts TCP connections on host:port."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host, port, timeout=30.0):
    t_end = time.time() + timeout
    while time.time() < t_end:
        if port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def connect(client, broker, port, subscriptions=(), name="client", keepalive=30, max_wait=None):
    """Connect with retry/back-off and (re)subscribe on EVERY connect.

    paho only restores the TCP session after a broker restart; subscriptions made outside
    on_connect are lost. Subscribing inside on_connect makes every node survive a broker
    restart or a network drop without manual intervention.
    """
    subscriptions = list(subscriptions)
    user_on_connect = client.on_connect

    def on_connect(c, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        if rc not in (0, None):
            print(f"[{name}] broker refused connection: {reason_code}", flush=True)
            return
        if subscriptions:
            c.subscribe(subscriptions)
        print(f"[{name}] connected to {broker}:{port}", flush=True)
        if user_on_connect:
            user_on_connect(c, userdata, flags, reason_code, properties)

    def on_disconnect(c, userdata, *args):
        reason = next((a for a in args if hasattr(a, "value") or isinstance(a, int)), 0)
        if getattr(reason, "value", reason) != 0:        # 0 = our own clean disconnect at shutdown
            print(f"[{name}] lost connection to the broker ({reason}) - reconnecting ...", flush=True)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    delay, t0 = 0.5, time.time()
    while True:
        try:
            client.connect(broker, port, keepalive)
            return client
        except OSError as e:
            if max_wait is not None and time.time() - t0 > max_wait:
                raise ConnectionError(f"[{name}] no MQTT broker at {broker}:{port} ({e})") from e
            print(f"[{name}] broker {broker}:{port} not reachable ({e}); retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 10)


def publish_command(cmd, broker=DEFAULT_BROKER, port=DEFAULT_PORT):
    """One-shot publish of a control command (used by control.py and the dashboard)."""
    c = make_client(f"shm-control-{os.getpid()}-{int(time.time() * 1000) % 100000}")
    c.connect(broker, port, 30)
    c.loop_start()
    try:
        info = c.publish(topic("control"), dumps(cmd), qos=1)
        info.wait_for_publish(5)
        if not info.is_published():
            raise TimeoutError("control command was not acknowledged by the broker")
    finally:
        c.loop_stop()
        c.disconnect()
