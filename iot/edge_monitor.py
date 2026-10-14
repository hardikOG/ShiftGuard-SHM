"""Edge analytics node: subscribes to the sensor network, runs ShiftGuard online.

For every window:
  1. collect the N accelerometer packets + temperature packet for that sequence number
  2. lost packets (wireless loss) are imputed by the masked-sensor model itself
  3. features -> ShiftGuard.step() -> attribution (NORMAL / ENVIRONMENT / SENSOR_FAULT / STRUCTURAL_DAMAGE)
  4. publish shm/<bridge>/status every window, shm/<bridge>/alert when a new alarm starts
  5. store everything in SQLite for the dashboard

  python iot/edge_monitor.py --model models/shiftguard_sim_ridge.pkl
"""
import argparse
import json
import os
import pickle
import sqlite3
import threading
import time

import numpy as np

from common import DEFAULT_BROKER, DEFAULT_PORT, dumps, make_client, topic
from shiftguard.features import window_features
from shiftguard.monitor import NORMAL

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (seq INTEGER PRIMARY KEY, ts REAL, t_hours REAL, temp REAL,
  label TEXT, fault_sensor INTEGER, ev_struct REAL, ev_env REAL, ev_sensor_max REAL, health REAL,
  severity TEXT, severity_set TEXT, location TEXT, sensor_scores TEXT, imputed TEXT,
  truth TEXT, baseline_alarm INTEGER, env_novel INTEGER);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, seq INTEGER,
  t_hours REAL, label TEXT, message TEXT);
"""


def alert_message(r, temp):
    if r["label"] == "STRUCTURAL_DAMAGE":
        sev = f" Severity: {r['severity']} (conformal set {r['severity_set']})." if r.get("severity") else ""
        return (f"STRUCTURAL DAMAGE suspected near sensors {r['damage_location']}.{sev} "
                f"Sensor faults ruled out by masking; temperature {temp:.1f} C is within experience. "
                f"Evidence {r['evidence_struct']:.0f} (alarm guarantee: E[time to false alarm] >= threshold). "
                f"Action: dispatch inspection.")
    if r["label"] == "SENSOR_FAULT":
        return (f"SENSOR FAULT on node S{r['fault_sensor']}: it disagrees with the rest of the network "
                f"while the structure is consistent. Action: check/replace node S{r['fault_sensor']}; "
                f"its readings are being imputed. No structural alarm raised.")
    if r["label"] == "ENVIRONMENT":
        return (f"UNPRECEDENTED ENVIRONMENT: temperature {temp:.1f} C is outside the conditions the model has "
                f"seen. Anomalies are attributed to weather; alarm held at low confidence. Action: monitor.")
    return "Back to normal."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default=DEFAULT_BROKER)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--model", default="models/shiftguard_sim_ridge.pkl")
    ap.add_argument("--db", default="state/live.db")
    args = ap.parse_args()

    with open(args.model, "rb") as f:
        pack = pickle.load(f)
    sg, base, cfg = pack["monitor"], pack["baseline"], pack["cfg"]
    sg.reset()
    N = cfg.n_sensors
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)
    db = sqlite3.connect(args.db, check_same_thread=False)
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")

    buf = {}              # seq -> {"acc": {i: arr}, "temp": float, "t": float, "truth": str}
    lock = threading.Lock()
    state = {"last_label": NORMAL, "processed": -1}
    client = make_client(f"shm-edge-{os.getpid()}")

    def process(seq):
        item = buf.pop(seq)
        a = np.zeros((N, cfg.win))
        missing = [i for i in range(N) if i not in item["acc"]]
        for i, arr in item["acc"].items():
            a[i, :len(arr)] = arr[:cfg.win]
        x = window_features(a, cfg)
        T = item.get("temp", float(np.median(sg.T_ref)))
        for i in missing:                                   # masked-sensor imputation of lost packets
            x[i] = sg.model.predict_sensor(x[None], np.array([T]), i)[0]
        r = sg.step(x, T)
        b = bool(base.alarms(x[None], 0.05)[0])
        db.execute("INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (seq, time.time(), item.get("t", seq), T, r["label"], r["fault_sensor"],
                    r["evidence_struct"], r["evidence_env"], max(r["evidence_sensors"]) / N, r["health_score"],
                    r["severity"], json.dumps(r["severity_set"]), json.dumps(r["damage_location"]),
                    json.dumps([round(v, 3) for v in r["sensor_scores"]]), json.dumps([i + 1 for i in missing]),
                    item.get("truth", ""), int(b), int(r["env_novel"])))
        status = dict(seq=seq, t_hours=item.get("t", seq), temp=T, **{k: r[k] for k in (
            "label", "fault_sensor", "health_score", "evidence_struct", "evidence_env", "severity",
            "severity_set", "damage_location", "env_novel")}, imputed=[i + 1 for i in missing])
        client.publish(topic("status"), dumps(status), qos=0)
        key = (r["label"], r["fault_sensor"])
        if key != state["last_label"]:            # every change of state is logged and published
            msg = alert_message(r, T)
            db.execute("INSERT INTO alerts (ts, seq, t_hours, label, message) VALUES (?,?,?,?,?)",
                       (time.time(), seq, item.get("t", seq), r["label"], msg))
            client.publish(topic("alert"), dumps(dict(seq=seq, t_hours=item.get("t", seq), label=r["label"],
                                                      message=msg, temp=T, bridge=topic().split("/")[1])), qos=1)
            print(f"[edge] t={item.get('t', seq):.0f}h {r['label']}: {msg}", flush=True)
            state["last_label"] = key
        db.commit()
        state["processed"] = seq

    def on_message(c, u, msg):
        try:
            d = json.loads(msg.payload)
        except Exception:
            return
        seq = int(d.get("seq", -1))
        if seq <= state["processed"]:
            return
        with lock:
            it = buf.setdefault(seq, {"acc": {}})
            if "/node/" in msg.topic:
                it["acc"][int(d["sensor"]) - 1] = np.asarray(d["data"], dtype=float)
                it["t"] = d.get("t_hours", seq)
            elif msg.topic.endswith("/env/temperature"):
                it["temp"] = float(d["temp"]); it["t"] = d.get("t_hours", seq)
            elif msg.topic.endswith("/truth"):
                it["truth"] = d.get("truth", "")
            # process complete windows; older incomplete ones are processed with imputation
            for s in sorted(buf):
                b = buf[s]
                complete = len(b["acc"]) == N and "temp" in b and "truth" in b
                stale = s < seq - 2
                if complete or (stale and b["acc"]):
                    process(s)
                elif stale:
                    buf.pop(s)

    client.on_message = on_message
    client.connect(args.broker, args.port, 60)
    client.subscribe([(topic("node", "+", "accel"), 0), (topic("env", "temperature"), 0), (topic("truth"), 0)])
    state["last_label"] = (NORMAL, None)
    print(f"[edge] ShiftGuard edge monitor running ({cfg.model} model) -> {args.db}", flush=True)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
