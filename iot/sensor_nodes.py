"""Virtual IoT sensor network.

Simulates N wireless accelerometer nodes + 1 temperature node on the bridge. Every
'hour' of bridge time each node publishes one 20 s acceleration window over MQTT:

  shm/<bridge>/node/<i>/accel        {"seq", "run", "t_hours", "sensor", "fs", "data": [...]}
  shm/<bridge>/env/temperature       {"seq", "run", "t_hours", "temp"}
  shm/<bridge>/truth                 {"seq", "run", "truth"}   (ground truth, for evaluation only)
  shm/<bridge>/sim/state             retained: what is currently injected (for the twin / dashboard)

Live fault / damage / weather injection is driven by the control topic
(shm/<bridge>/control) - from iot/control.py, the dashboard or the digital twin. An external
temperature node (e.g. the Wokwi ESP32 + DHT22 sketch, via iot/wokwi_relay.py) can override the
temperature by publishing {"temp": x} on shm/<bridge>/env/override.

  python iot/sensor_nodes.py --rate 4          # 4 windows per second (1 bridge-day every 6 s)
"""
import argparse
import json
import threading
import time

import numpy as np

from common import DEFAULT_BROKER, DEFAULT_PORT, connect, dumps, make_client, topic
from shiftguard import Config
from shiftguard.environment import temperature_profile
from shiftguard.faults import inject, FAULT_KINDS

OVERRIDE_TTL_S = 30.0          # an external temperature node counts as live for this long
MIN_RATE, MAX_RATE = 0.2, 50.0


class LiveState:
    """Everything an operator can inject. Commands arrive on the MQTT thread, the publishing loop
    reads the state on the main thread, so every access goes through one lock."""

    def __init__(self, rate, n_sensors):
        self.lock = threading.Lock()
        self.rate = rate
        self.N = n_sensors
        self.faults = []            # dicts: kind, sensor (0-based), start, until, severity
        self.damage = 0
        self.cold = None            # (delta, start, until)
        self.override_temp = None
        self.override_at = 0.0
        self.packet_loss = 0.0
        self.paused = False
        self.changed = True

    def handle(self, cmd, t):
        """Apply one control command. Invalid commands are rejected with a message, never raised:
        a typo on the control topic must not take the sensor network down."""
        try:
            self._handle(cmd, t)
        except (TypeError, ValueError) as e:
            print(f"[nodes] rejected command {cmd}: {e}", flush=True)

    def _handle(self, cmd, t):
        c = cmd.get("cmd")
        with self.lock:
            if c == "fault":
                kind = cmd.get("kind", "drift")
                if kind not in FAULT_KINDS:
                    raise ValueError(f"unknown fault kind {kind!r}")
                s = int(cmd.get("sensor", 3))
                if not 1 <= s <= self.N:
                    raise ValueError(f"sensor must be 1..{self.N}")
                hours = float(cmd.get("hours", 48))
                sev = float(cmd.get("severity", 1.0))
                if hours <= 0 or not 0 < sev <= 5:
                    raise ValueError("hours must be > 0 and 0 < severity <= 5")
                self.faults = [f for f in self.faults if f["sensor"] != s - 1]
                self.faults.append(dict(kind=kind, sensor=s - 1, start=t, until=t + hours, severity=sev))
            elif c == "repair_sensor":
                s = int(cmd.get("sensor", 0))
                self.faults = [f for f in self.faults if f["sensor"] != s - 1]
            elif c == "damage":
                level = int(cmd.get("level", 1))
                if level not in (0, 1, 2):
                    raise ValueError("damage level must be 0, 1 or 2")
                self.damage = level
            elif c == "coldsnap":
                h = float(cmd.get("hours", 72))
                delta = float(cmd.get("delta", -10))
                if h <= 0 or not -40 <= delta <= 40:
                    raise ValueError("hours must be > 0 and -40 <= delta <= 40")
                self.cold = (delta, t, t + h)
            elif c == "packet_loss":
                p = float(cmd.get("p", 0.05))
                if not 0 <= p <= 0.5:
                    raise ValueError("packet loss must be between 0 and 0.5")
                self.packet_loss = p
            elif c == "speed":
                r = float(cmd.get("rate", self.rate))
                self.rate = float(np.clip(r, MIN_RATE, MAX_RATE))
            elif c == "pause":
                self.paused = True
            elif c == "resume":
                self.paused = False
            elif c == "clear":
                self.faults, self.damage, self.cold, self.packet_loss = [], 0, None, 0.0
            else:
                raise ValueError(f"unknown command {c!r}")
            self.changed = True
        print(f"[nodes] t={t:.0f}h command: {cmd}", flush=True)

    def snapshot(self, t, T):
        with self.lock:
            return dict(t_hours=t, temp=round(float(T), 2), rate=self.rate, paused=self.paused,
                        damage=self.damage, packet_loss=self.packet_loss,
                        coldsnap=(dict(delta=self.cold[0], until=self.cold[2]) if self.cold and self.cold[2] > t else None),
                        faults=[dict(sensor=f["sensor"] + 1, kind=f["kind"], until=f["until"]) for f in self.faults],
                        override=self.override_temp is not None and time.time() - self.override_at < OVERRIDE_TTL_S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default=DEFAULT_BROKER)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--source", default="sim", choices=["sim", "z24"])
    ap.add_argument("--z24-dir", default=None)
    ap.add_argument("--z24-setup", default="0")
    ap.add_argument("--rate", type=float, default=4.0, help="windows (bridge-hours) per real second")
    ap.add_argument("--start-day", type=float, default=60.0, help="day of year the stream starts")
    ap.add_argument("--hours", type=int, default=0, help="stop after this many windows (0 = run forever)")
    ap.add_argument("--seed", type=int, default=123)
    args = ap.parse_args()

    from shiftguard.sources import make_source
    cfg = Config()
    setup = args.z24_setup if args.z24_setup == "all" else int(args.z24_setup)
    src = make_source(cfg, args.source, args.z24_dir, setup)
    rng = np.random.default_rng(args.seed)
    temps = temperature_profile(24 * 365 * 3, rng, start_hour=int(args.start_day * 24))
    st = LiveState(float(np.clip(args.rate, MIN_RATE, MAX_RATE)), cfg.n_sensors)
    run_id = f"{int(time.time())}-{args.seed}"

    client = make_client(f"shm-nodes-{args.seed}-{int(time.time()) % 100000}")
    t_now = [0.0]

    def on_message(c, u, msg):
        try:
            data = json.loads(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(data, dict):
            return
        if msg.topic.endswith("/control"):
            st.handle(data, t_now[0])
        elif msg.topic.endswith("/env/override") and "temp" in data:
            try:
                temp = float(data["temp"])
            except (TypeError, ValueError):
                return
            if -50 <= temp <= 60:
                with st.lock:
                    st.override_temp, st.override_at = temp, time.time()

    client.on_message = on_message
    connect(client, args.broker, args.port, [(topic("control"), 1), (topic("env", "override"), 0)], name="nodes")
    client.loop_start()
    print(f"[nodes] {cfg.n_sensors} accelerometer nodes + 1 temperature node publishing to "
          f"{args.broker}:{args.port} at {st.rate} windows/s (source: {src.name})", flush=True)

    seq = 0
    try:
        while args.hours == 0 or seq < args.hours:
            t0 = time.time()
            if st.paused:
                if st.changed:
                    client.publish(topic("sim", "state"), dumps(st.snapshot(t_now[0], temps[seq % len(temps)])), qos=1, retain=True)
                    st.changed = False
                time.sleep(0.1)
                continue
            t = float(seq); t_now[0] = t
            T = float(temps[seq % len(temps)])
            with st.lock:
                cold = st.cold
                if cold and cold[1] <= t < cold[2]:
                    T += cold[0] * np.sin(np.pi * (t - cold[1]) / (cold[2] - cold[1]))
                if st.override_temp is not None and time.time() - st.override_at < OVERRIDE_TTL_S:
                    T = st.override_temp
                expired = [f for f in st.faults if f["until"] <= t]
                st.faults = [f for f in st.faults if f["until"] > t]
                faults, damage, loss, rate = list(st.faults), st.damage, st.packet_loss, st.rate
                if expired:
                    st.changed = True
            a = src.window(T, damage, rng, split="stream")
            truth = "healthy"
            if cold and cold[1] <= t < cold[2]:
                truth = "env-coldsnap"
            for f in faults:
                a = inject(a, f["sensor"], f["kind"], rng, severity=f["severity"], progress=(t - f["start"]) / 24)
                truth = f"fault-s{f['sensor'] + 1}-{f['kind']}"
            if damage:
                truth = "damage-moderate" if damage == 1 else "damage-severe"
            for i in range(cfg.n_sensors):
                if loss and rng.uniform() < loss:
                    continue                                    # simulated wireless packet loss
                client.publish(topic("node", i + 1, "accel"),
                               dumps(dict(seq=seq, run=run_id, t_hours=t, sensor=i + 1, fs=cfg.fs,
                                          data=np.round(a[i].astype(np.float32), 6).tolist())), qos=0)
            client.publish(topic("env", "temperature"), dumps(dict(seq=seq, run=run_id, t_hours=t, temp=round(T, 2))), qos=0)
            client.publish(topic("truth"), dumps(dict(seq=seq, run=run_id, truth=truth)), qos=0)
            if st.changed or seq % 24 == 0:
                client.publish(topic("sim", "state"), dumps(st.snapshot(t, T)), qos=1, retain=True)
                st.changed = False
            seq += 1
            time.sleep(max(0.0, 1.0 / rate - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop(); client.disconnect()


if __name__ == "__main__":
    main()
