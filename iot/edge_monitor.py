"""Edge analytics node: subscribes to the sensor network, runs ShiftGuard online.

For every window:
  1. collect the N accelerometer packets + temperature packet for that sequence number
  2. lost packets (wireless loss) are imputed by the masked-sensor model itself
  3. features -> ShiftGuard.step() -> attribution (NORMAL / ENVIRONMENT / SENSOR_FAULT / STRUCTURAL_DAMAGE)
  4. publish shm/<bridge>/status every window, shm/<bridge>/alert when the attribution changes
  5. store everything in SQLite for the dashboard

Windows are always processed in sequence order (the e-detectors are sequential tests), a window
is processed as soon as it is complete, or with imputation once it is 2 windows late.

  python iot/edge_monitor.py --model models/shiftguard_sim_ridge.pkl
"""
import argparse
import json
import os
import pickle
import sqlite3
import sys
import threading
import time

import numpy as np

from common import DEFAULT_BROKER, DEFAULT_PORT, connect, dumps, make_client, topic
from shiftguard.features import window_features
from shiftguard.monitor import NORMAL

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (seq INTEGER PRIMARY KEY, ts REAL, t_hours REAL, temp REAL,
  label TEXT, fault_sensor INTEGER, ev_struct REAL, ev_env REAL, ev_sensor_max REAL, health REAL,
  severity TEXT, severity_set TEXT, location TEXT, sensor_scores TEXT, imputed TEXT,
  truth TEXT, baseline_alarm INTEGER, env_novel INTEGER, proc_ms REAL);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, seq INTEGER,
  t_hours REAL, label TEXT, message TEXT);
"""
LATE_WINDOWS = 2           # a window this many sequence numbers behind the newest is processed as-is
MIN_SENSORS_FRACTION = 0.5  # fewer packets than this -> the window is dropped, not imputed


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


def assemble_features(acc, N, cfg, sg, T):
    """Features for one window from the packets that arrived; lost sensors are imputed.

    Features are computed from the received channels only (the excitation normalisation is a median
    over sensors, so a zero-filled channel would bias it), then each missing sensor is predicted
    from the others by the masked-sensor model. Two passes so that, with several missing sensors,
    each imputation also sees the others' imputed values instead of the reference fill.
    """
    received = sorted(acc)
    missing = [i for i in range(N) if i not in acc]
    a = np.zeros((len(received), cfg.win))
    for row, i in enumerate(received):
        arr = acc[i][:cfg.win]
        a[row, :len(arr)] = arr
    x = np.array(getattr(sg, "x_ref", np.zeros((N, cfg.n_bands))), dtype=float)
    x[received] = window_features(a, cfg)
    for _ in range(2 if len(missing) > 1 else 1):
        for i in missing:
            x[i] = sg.model.predict_sensor(x[None], np.array([T]), i)[0]
    return x, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default=DEFAULT_BROKER)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--model", default="models/shiftguard_sim_ridge.pkl")
    ap.add_argument("--db", default="state/live.db")
    ap.add_argument("--resume", action="store_true", help="keep the existing database and append to it")
    args = ap.parse_args()

    if not os.path.exists(args.model):
        sys.exit(f"[edge] model file {args.model} not found - run scripts/train_monitor.py first")
    with open(args.model, "rb") as f:
        pack = pickle.load(f)
    sg, base, cfg = pack["monitor"], pack["baseline"], pack["cfg"]
    sg.reset()
    N = cfg.n_sensors
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    if not args.resume:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(args.db + suffix):
                os.remove(args.db + suffix)
    db = sqlite3.connect(args.db, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)

    buf = {}              # seq -> {"acc": {i: arr}, "temp": float, "t": float, "truth": str}
    lock = threading.Lock()
    # Stream positions are stored as offset + seq, so a restarted sensor network (seq back to 0) or a
    # restarted edge monitor (--resume) appends to the history instead of overwriting it.
    state = {"last_label": (NORMAL, None, None), "processed": -1, "newest": -1, "run": None, "has_truth": False,
             "dropped": 0, "offset": 0, "t_offset": 0.0}
    client = make_client(f"shm-edge-{os.getpid()}")

    def process(seq, item):
        t_start = time.perf_counter()
        T = item.get("temp", float(np.median(sg.T_ref)))
        x, missing = assemble_features(item["acc"], N, cfg, sg, T)
        r = sg.step(x, T)
        proc_ms = (time.perf_counter() - t_start) * 1e3
        b = bool(base.alarms(x[None], 0.05)[0])
        t_h = state["t_offset"] + item.get("t", seq)
        seq = state["offset"] + seq
        db.execute("INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (seq, time.time(), t_h, T, r["label"], r["fault_sensor"],
                    r["evidence_struct"], r["evidence_env"], max(r["evidence_sensors"]) / N, r["health_score"],
                    r["severity"], json.dumps(r["severity_set"]), json.dumps(r["damage_location"]),
                    json.dumps([round(v, 3) for v in r["sensor_scores"]]), json.dumps([i + 1 for i in missing]),
                    item.get("truth", ""), int(b), int(r["env_novel"]), proc_ms))
        status = dict(seq=seq, t_hours=t_h, temp=T, **{k: r[k] for k in (
            "label", "fault_sensor", "health_score", "evidence_struct", "evidence_env", "severity",
            "severity_set", "damage_location", "env_novel")}, imputed=[i + 1 for i in missing],
            sensor_scores=[round(v, 3) for v in r["sensor_scores"]],
            evidence_sensors=[round(v / N, 4) for v in r["evidence_sensors"]],
            alarm_level=cfg.alarm_level, baseline_alarm=b, truth=item.get("truth", ""), proc_ms=round(proc_ms, 2))
        client.publish(topic("status"), dumps(status), qos=0)
        key = (r["label"], r["fault_sensor"], r["severity"])
        if key != state["last_label"]:            # every change of state (incl. severity escalation) is published
            msg = alert_message(r, T)
            db.execute("INSERT INTO alerts (ts, seq, t_hours, label, message) VALUES (?,?,?,?,?)",
                       (time.time(), seq, t_h, r["label"], msg))
            client.publish(topic("alert"), dumps(dict(seq=seq, t_hours=t_h, label=r["label"],
                                                      message=msg, temp=T, bridge=topic().split("/")[1])), qos=1, retain=True)
            print(f"[edge] t={t_h:.0f}h {r['label']}: {msg}", flush=True)
            state["last_label"] = key
        db.commit()

    def drain():
        """Process buffered windows strictly in sequence order."""
        while buf:
            s = min(buf)
            b = buf[s]
            complete = len(b["acc"]) == N and "temp" in b and ("truth" in b or not state["has_truth"])
            late = s <= state["newest"] - LATE_WINDOWS
            if not (complete or late):
                return
            buf.pop(s)
            state["processed"] = s
            if len(b["acc"]) >= max(1, int(np.ceil(MIN_SENSORS_FRACTION * N))):
                try:
                    process(s, b)
                except Exception as e:  # noqa: BLE001 - one bad window must not stop monitoring
                    print(f"[edge] window {s} failed: {type(e).__name__}: {e}", flush=True)
            else:
                state["dropped"] += 1
                print(f"[edge] window {s} dropped: only {len(b['acc'])}/{N} sensor packets arrived", flush=True)

    def on_message(c, u, msg):
        try:
            d = json.loads(msg.payload)
            seq = int(d.get("seq", -1))
        except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
            return
        if seq < 0:
            return
        with lock:
            run = d.get("run")
            if run is not None and run != state["run"]:
                if state["run"] is not None:     # the sensor network restarted: start a new stream
                    print(f"[edge] sensor network restarted (run {run}); continuing monitoring", flush=True)
                row = db.execute("SELECT MAX(seq), MAX(t_hours) FROM windows").fetchone()
                if row[0] is not None:           # continue the stored history without a gap
                    state["offset"] = int(row[0]) + 1 - seq
                    state["t_offset"] = float(row[1]) + 1 - float(d.get("t_hours", seq))
                state["run"] = run
                buf.clear()
                state["processed"], state["newest"] = -1, -1
            if msg.topic.endswith("/truth"):
                # must be set before the 'already processed' check below, otherwise the edge never
                # learns that this sensor network publishes ground truth and never waits for it
                state["has_truth"] = True
            if seq <= state["processed"]:
                return
            it = buf.setdefault(seq, {"acc": {}})
            try:
                if "/node/" in msg.topic:
                    i = int(d["sensor"]) - 1
                    if 0 <= i < N:
                        it["acc"][i] = np.asarray(d["data"], dtype=float)
                    it["t"] = float(d.get("t_hours", seq))
                elif msg.topic.endswith("/env/temperature"):
                    it["temp"] = float(d["temp"]); it["t"] = float(d.get("t_hours", seq))
                elif msg.topic.endswith("/truth"):
                    it["truth"] = str(d.get("truth", ""))
            except (KeyError, TypeError, ValueError):
                return
            state["newest"] = max(state["newest"], seq)
            drain()

    client.on_message = on_message
    connect(client, args.broker, args.port,
            [(topic("node", "+", "accel"), 0), (topic("env", "temperature"), 0), (topic("truth"), 0)], name="edge")
    print(f"[edge] ShiftGuard edge monitor running ({cfg.model} model) -> {args.db}", flush=True)
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
