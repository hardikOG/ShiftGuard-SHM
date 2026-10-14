"""System tests: the trained monitor, the IoT helpers and the live MQTT pipeline.

  python -m pytest -q tests                 # everything (~1-2 min)
  python -m pytest -q tests -m "not slow"   # skip the multi-process MQTT test
"""
import os
import pickle
import socket
import sqlite3
import subprocess
import sys
import time

import numpy as np
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "iot"))

from shiftguard import Config  # noqa: E402
from shiftguard.faults import inject  # noqa: E402
from shiftguard.features import window_features  # noqa: E402
from shiftguard.monitor import ShiftGuard, NORMAL, ENV, FAULT, DAMAGE  # noqa: E402
from shiftguard.scenario import build_timeline, generate_features, training_year  # noqa: E402
from shiftguard.sources import VirtualBridge  # noqa: E402


@pytest.fixture(scope="module")
def trained():
    """A small but real monitor: 90 healthy days, ridge model."""
    cfg = Config(model="ridge", seed=0, local_k=200)
    rng = np.random.default_rng(0)
    src = VirtualBridge(cfg)
    Xf, Tf, Xc, Tc = training_year(src, cfg, rng, n_hours=24 * 90)
    return cfg, src, ShiftGuard(cfg).fit(Xf, Tf, Xc, Tc)


def _stream(cfg, src, events, hours, seed):
    rng = np.random.default_rng(seed)
    T, D, F, Y = build_timeline(hours, rng, events, start_hour=0)
    return generate_features(src, cfg, T, D, F, rng, "stream"), T, Y


def test_sensor_fault_is_attributed_to_the_right_sensor_and_not_to_damage(trained):
    cfg, src, sg = trained
    X, T, Y = _stream(cfg, src, [{"type": "fault", "kind": "noise", "sensor": 6, "start_day": 2, "end_day": 5}], 24 * 7, 1)
    out, _ = sg.run(X, T)
    labels = np.array([o["label"] for o in out])
    fault = np.array([str(y).startswith("fault") for y in Y])
    assert (labels[fault] == DAMAGE).mean() == 0
    hit = [o["fault_sensor"] == 6 for o, f in zip(out, fault) if f and o["label"] == FAULT]
    assert len(hit) > 0.6 * fault.sum() and np.mean(hit) > 0.9


def test_fault_does_not_leave_evidence_on_neighbours(trained):
    """Regression: neighbours of a faulty sensor must not accumulate evidence (mask-and-impute)."""
    cfg, src, sg = trained
    X, T, Y = _stream(cfg, src, [{"type": "fault", "kind": "drift", "sensor": 3, "start_day": 1, "end_day": 4}], 24 * 6, 2)
    out, _ = sg.run(X, T)
    after = [o for o, y in zip(out, Y) if y == "healthy"][24 * 1 + 12:]          # 12 h after the fault ended
    assert all(o["label"] == NORMAL for o in after)
    peak_neighbour = max(max(o["evidence_sensors"][1], o["evidence_sensors"][3]) for o in out)
    assert peak_neighbour < cfg.alarm_level * cfg.n_sensors


def test_damage_is_detected_and_localised(trained):
    cfg, src, sg = trained
    X, T, Y = _stream(cfg, src, [{"type": "damage", "level": 2, "start_day": 1, "end_day": 3}], 24 * 3, 3)
    out, _ = sg.run(X, T)
    dmg = [o for o, y in zip(out, Y) if str(y).startswith("damage")]
    first = next(i for i, o in enumerate(dmg) if o["label"] == DAMAGE)
    assert first < 12
    assert any(s in (5, 6) for s in dmg[first + 5]["damage_location"])


def test_unseen_cold_is_attributed_to_environment_not_damage(trained):
    cfg, src, sg = trained
    T = np.full(24 * 2, sg.T_ref.min() - 15.0)            # far colder than anything in calibration
    rng = np.random.default_rng(4)
    X = np.stack([window_features(src.window(t, 0, rng), cfg) for t in T])
    out, _ = sg.run(X, T)
    labels = [o["label"] for o in out]
    assert DAMAGE not in labels and ENV in labels


def test_healthy_stream_raises_no_alarm(trained):
    cfg, src, sg = trained
    X, T, _ = _stream(cfg, src, [], 24 * 10, 5)
    out, _ = sg.run(X, T)
    assert sum(o["label"] != NORMAL for o in out) == 0


def test_online_step_matches_offline_run(trained):
    cfg, src, sg = trained
    X, T, _ = _stream(cfg, src, [{"type": "fault", "kind": "spikes", "sensor": 2, "start_day": 0.5, "end_day": 1}], 36, 6)
    offline, _ = sg.run(X, T)
    sg.reset()
    online = [sg.step(x, t) for x, t in zip(X, T)]
    assert [o["label"] for o in online] == [o["label"] for o in offline]
    # smoothed conformal p-values use a random tie-break, so evidence agrees only up to that randomness
    on, off = (np.log10([o["evidence_struct"] for o in r]) for r in (online, offline))
    assert np.allclose(on, off, atol=0.5)


def test_monitor_pickles_with_global_calibration(trained):
    cfg, src, sg = trained
    import copy
    import dataclasses
    g = copy.copy(sg); g.cfg = dataclasses.replace(cfg, local_k=0)
    rng = np.random.default_rng(7)
    Xc = np.stack([window_features(src.window(10.0, 0, rng), cfg) for _ in range(300)])
    g.calibrate(Xc, np.full(300, 10.0))
    clone = pickle.loads(pickle.dumps(g))
    assert clone.step(Xc[0], 10.0)["label"] == NORMAL


def test_lost_packets_are_imputed_close_to_the_truth(trained):
    from edge_monitor import assemble_features
    cfg, src, sg = trained
    rng = np.random.default_rng(8)
    a = src.window(12.0, 0, rng)
    full = window_features(a, cfg)
    acc = {i: a[i] for i in range(cfg.n_sensors) if i not in (2, 6)}
    x, missing = assemble_features(acc, cfg.n_sensors, cfg, sg, 12.0)
    assert missing == [2, 6]
    err_imputed = np.abs(x[[2, 6]] - full[[2, 6]]).mean()
    err_reference = np.abs(sg.x_ref[[2, 6]] - full[[2, 6]]).mean()
    assert err_imputed < err_reference
    r = sg.step(x, 12.0)
    assert r["label"] == NORMAL
    sg.reset()


def test_live_state_rejects_bad_commands():
    from sensor_nodes import LiveState
    st = LiveState(4.0, 8)
    for bad in [{"cmd": "fault", "kind": "melt"}, {"cmd": "fault", "sensor": 99}, {"cmd": "damage", "level": 7},
                {"cmd": "packet_loss", "p": 3}, {"cmd": "coldsnap", "hours": -1}, {"cmd": "nope"},
                {"cmd": "fault", "sensor": "x"}]:
        st.handle(bad, 0.0)                                  # must not raise
    assert st.faults == [] and st.damage == 0 and st.packet_loss == 0
    st.handle({"cmd": "speed", "rate": 0}, 0.0)              # would divide by zero if not clamped
    assert st.rate > 0
    st.handle({"cmd": "fault", "kind": "noise", "sensor": 4, "hours": 5}, 10.0)
    st.handle({"cmd": "fault", "kind": "drift", "sensor": 4}, 11.0)     # replaces, does not stack
    assert [(f["sensor"], f["kind"]) for f in st.faults] == [(3, "drift")]
    st.handle({"cmd": "repair_sensor", "sensor": 4}, 12.0)
    assert st.faults == []


def test_fault_injection_rejects_unknown_kind():
    with pytest.raises(ValueError):
        inject(np.zeros((8, 64)), 0, "melt", np.random.default_rng(0))


# ------------------------------------------------------------------------- live MQTT pipeline
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.slow
def test_live_pipeline_over_mqtt(trained, tmp_path):
    """Broker -> virtual sensor nodes -> edge monitor -> SQLite, as separate processes, including a
    control command, packet loss, and a restart of the sensor network."""
    from common import publish_command, wait_for_port
    cfg, src, sg = trained
    model = tmp_path / "m.pkl"
    from shiftguard.baselines import PerWindowAE
    rng = np.random.default_rng(0)
    Xb = np.stack([window_features(src.window(10.0, 0, rng), cfg) for _ in range(200)])
    with open(model, "wb") as f:
        pickle.dump(dict(monitor=sg, baseline=PerWindowAE(seed=0).fit(Xb[:100], Xb[100:]), cfg=cfg, source="sim"), f)
    port, ws = _free_port(), _free_port()
    db = tmp_path / "live.db"
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    py = sys.executable
    procs = [subprocess.Popen([py, "iot/broker.py", "--port", str(port), "--ws-port", str(ws)], cwd=ROOT, env=env)]
    try:
        assert wait_for_port("127.0.0.1", port, 30)
        procs.append(subprocess.Popen([py, "iot/edge_monitor.py", "--model", str(model), "--db", str(db),
                                       "--port", str(port)], cwd=ROOT, env=env))
        time.sleep(4)
        nodes = [py, "iot/sensor_nodes.py", "--rate", "20", "--port", str(port), "--hours"]
        n1 = subprocess.Popen(nodes + ["120"], cwd=ROOT, env=env)
        time.sleep(3)
        publish_command({"cmd": "packet_loss", "p": 0.2}, "localhost", port)
        n1.wait(60)
        time.sleep(2)
        n2 = subprocess.Popen(nodes + ["20"], cwd=ROOT, env=env)    # restarted network
        n2.wait(60)
        time.sleep(2)
        con = sqlite3.connect(db)
        rows = con.execute("SELECT seq, t_hours, imputed, truth FROM windows ORDER BY seq").fetchall()
        con.close()
        seqs = [r[0] for r in rows]
        assert len(rows) >= 125                                  # few windows lost even with 20 % packet loss
        assert seqs == sorted(set(seqs)) and seqs[-1] >= 135    # restart appended, did not overwrite
        assert any(r[2] != "[]" for r in rows)                  # lost packets were imputed
        assert sum(r[3] == "healthy" for r in rows) > 100       # ground truth reached the edge
    finally:
        for p in procs[::-1]:
            p.terminate()
            p.wait(10)
