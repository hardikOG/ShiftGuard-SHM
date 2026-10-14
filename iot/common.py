"""Shared MQTT settings and helpers for the live AIoT pipeline."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_BROKER = os.environ.get("SHM_BROKER", "localhost")
DEFAULT_PORT = int(os.environ.get("SHM_PORT", "1883"))
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


def publish_command(cmd, broker=DEFAULT_BROKER, port=DEFAULT_PORT):
    """One-shot publish of a control command (used by control.py and the dashboard)."""
    c = make_client(f"shm-control-{os.getpid()}")
    c.connect(broker, port, 30)
    c.loop_start()
    info = c.publish(topic("control"), dumps(cmd), qos=1)
    info.wait_for_publish(5)
    c.loop_stop()
    c.disconnect()
