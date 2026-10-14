"""Virtual IoT sensor network.

Simulates N wireless accelerometer nodes + 1 temperature node on the bridge. Every
'hour' of bridge time each node publishes one 20 s acceleration window over MQTT:

  shm/<bridge>/node/<i>/accel        {"seq", "t_hours", "sensor", "fs", "data": [...]}
  shm/<bridge>/env/temperature       {"seq", "t_hours", "temp"}
  shm/<bridge>/truth                 {"seq", "truth"}        (ground truth, for evaluation only)

Live fault / damage / weather injection is driven by the control topic
(shm/<bridge>/control) - from iot/control.py or the dashboard buttons. An external
temperature node (e.g. the Wokwi ESP32 + DHT22 sketch) can override the temperature by
publishing {"temp": x} on shm/<bridge>/env/override.

  python iot/sensor_nodes.py --rate 4          # 4 windows per second (1 bridge-day every 6 s)
"""
import argparse
import json
import time

import numpy as np

from common import DEFAULT_BROKER, DEFAULT_PORT, dumps, make_client, topic
from shiftguard import Config
from shiftguard.environment import temperature_profile
from shiftguard.faults import inject, FAULT_KINDS
from shiftguard.sources import make_source


class LiveState:
    def __init__(self, rate):
        self.rate = rate
        self.faults = []            # dicts: kind, sensor (0-based), until, start
        self.damage = 0
        self.cold = None            # (delta, start, until)
        self.override_temp = None
        self.override_at = 0.0
        self.packet_loss = 0.0

    def handle(self, cmd, t):
        c = cmd.get("cmd")
        if c == "fault":
            kind = cmd.get("kind", "drift")
            if kind not in FAULT_KINDS:
                print(f"[nodes] unknown fault kind {kind}"); return
            s = int(cmd.get("sensor", 3)) - 1
            self.faults = [f for f in self.faults if f["sensor"] != s]
            self.faults.append(dict(kind=kind, sensor=s, start=t, until=t + float(cmd.get("hours", 48)),
                                    severity=float(cmd.get("severity", 1.0))))
        elif c == "damage":
            self.damage = int(cmd.get("level", 1))
        elif c == "coldsnap":
            h = float(cmd.get("hours", 72))
            self.cold = (float(cmd.get("delta", -10)), t, t + h)
        elif c == "packet_loss":
            self.packet_loss = float(cmd.get("p", 0.05))
        elif c == "speed":
            self.rate = float(cmd.get("rate", self.rate))
        elif c == "clear":
            self.faults, self.damage, self.cold, self.packet_loss = [], 0, None, 0.0
        print(f"[nodes] t={t:.0f}h command: {cmd}", flush=True)


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

    cfg = Config()
    setup = args.z24_setup if args.z24_setup == "all" else int(args.z24_setup)
    src = make_source(cfg, args.source, args.z24_dir, setup)
    rng = np.random.default_rng(args.seed)
    temps = temperature_profile(24 * 365 * 3, rng, start_hour=int(args.start_day * 24))
    st = LiveState(args.rate)

    client = make_client(f"shm-nodes-{args.seed}")
    t_now = [0.0]

    def on_message(c, u, msg):
        try:
            data = json.loads(msg.payload)
        except Exception:
            return
        if msg.topic.endswith("/control"):
            st.handle(data, t_now[0])
        elif msg.topic.endswith("/env/override") and "temp" in data:
            st.override_temp, st.override_at = float(data["temp"]), time.time()

    client.on_message = on_message
    client.connect(args.broker, args.port, 60)
    client.subscribe([(topic("control"), 1), (topic("env", "override"), 0)])
    client.loop_start()
    print(f"[nodes] {cfg.n_sensors} accelerometer nodes + 1 temperature node publishing to "
          f"{args.broker}:{args.port} at {args.rate} windows/s", flush=True)

    seq = 0
    try:
        while args.hours == 0 or seq < args.hours:
            t0 = time.time()
            t = float(seq); t_now[0] = t
            T = float(temps[seq % len(temps)])
            if st.cold and st.cold[1] <= t < st.cold[2]:
                T += st.cold[0] * np.sin(np.pi * (t - st.cold[1]) / (st.cold[2] - st.cold[1]))
            if st.override_temp is not None and time.time() - st.override_at < 30:
                T = st.override_temp
            a = src.window(T, st.damage, rng, split="stream")
            truth = "healthy"
            if st.cold and st.cold[1] <= t < st.cold[2]:
                truth = "env-coldsnap"
            st.faults = [f for f in st.faults if f["until"] > t]
            for f in st.faults:
                a = inject(a, f["sensor"], f["kind"], rng, severity=f["severity"], progress=(t - f["start"]) / 24)
                truth = f"fault-s{f['sensor'] + 1}-{f['kind']}"
            if st.damage:
                truth = "damage-moderate" if st.damage == 1 else "damage-severe"
            for i in range(cfg.n_sensors):
                if st.packet_loss and rng.uniform() < st.packet_loss:
                    continue                                    # simulated wireless packet loss
                client.publish(topic("node", i + 1, "accel"),
                               dumps(dict(seq=seq, t_hours=t, sensor=i + 1, fs=cfg.fs,
                                          data=np.round(a[i].astype(np.float32), 6).tolist())), qos=0)
            client.publish(topic("env", "temperature"), dumps(dict(seq=seq, t_hours=t, temp=round(T, 2))), qos=0)
            client.publish(topic("truth"), dumps(dict(seq=seq, truth=truth)), qos=0)
            seq += 1
            time.sleep(max(0.0, 1.0 / st.rate - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop(); client.disconnect()


if __name__ == "__main__":
    main()
