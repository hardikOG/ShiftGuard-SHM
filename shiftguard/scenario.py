"""Monitoring timelines: temperature + scheduled events (faults, cold snaps, damage) -> stream.

Each hour produces one window. Ground truth per hour is one of:
  healthy | env-coldsnap | fault-s<k>-<kind> | damage-moderate | damage-severe
"""
import json
import numpy as np

from .environment import temperature_profile, apply_coldsnap
from .faults import inject
from .features import window_features

HOURS_PER_YEAR = 365 * 24

DEFAULT_EVENTS = [
    {"type": "coldsnap", "start_day": 15, "end_day": 22, "delta": -9},
    {"type": "fault", "kind": "drift", "sensor": 3, "start_day": 120, "end_day": 134},
    {"type": "fault", "kind": "noise", "sensor": 6, "start_day": 200, "end_day": 204},
    {"type": "fault", "kind": "dropout", "sensor": 1, "start_day": 260, "end_day": 262},
    {"type": "fault", "kind": "spikes", "sensor": 4, "start_day": 285, "end_day": 288},
    {"type": "fault", "kind": "clipping", "sensor": 7, "start_day": 300, "end_day": 303},
    {"type": "damage", "level": 1, "start_day": 330, "end_day": 348},
    {"type": "damage", "level": 2, "start_day": 348, "end_day": 366},
]


def load_events(path_or_none):
    if path_or_none is None:
        return DEFAULT_EVENTS
    with open(path_or_none) as f:
        return json.load(f)


def build_timeline(n_hours, rng, events, start_hour=0):
    """Returns temperature (n,), damage level (n,), fault list per hour, truth labels (n,)."""
    T = temperature_profile(n_hours, rng, start_hour=start_hour)
    dmg = np.zeros(n_hours, int)
    faults = [[] for _ in range(n_hours)]
    truth = np.array(["healthy"] * n_hours, dtype=object)
    d = np.arange(n_hours) / 24.0
    for ev in events:
        m = (d >= ev["start_day"]) & (d < ev["end_day"])
        if ev["type"] == "coldsnap":
            T = apply_coldsnap(T, ev["start_day"], ev["end_day"], ev["delta"])
            truth[m & (truth == "healthy")] = "env-coldsnap"
        elif ev["type"] == "damage":
            dmg[m] = ev["level"]
            truth[m] = "damage-moderate" if ev["level"] == 1 else "damage-severe"
        elif ev["type"] == "fault":
            for t in np.where(m)[0]:
                faults[t].append(dict(kind=ev["kind"], sensor=ev["sensor"] - 1,
                                      progress=d[t] - ev["start_day"], severity=ev.get("severity", 1.0)))
            truth[m & (dmg == 0)] = f"fault-s{ev['sensor']}-{ev['kind']}"
    return T, dmg, faults, truth


def generate_features(source, cfg, T, dmg, faults, rng, split="stream", progress_every=0):
    X = np.zeros((len(T), cfg.n_sensors, cfg.n_bands))
    for t in range(len(T)):
        a = source.window(T[t], dmg[t], rng, split=split)
        for f in faults[t]:
            a = inject(a, f["sensor"], f["kind"], rng, severity=f["severity"], progress=f["progress"])
        X[t] = window_features(a, cfg)
        if progress_every and t % progress_every == 0:
            print(f"    {split}: {t}/{len(T)} windows", flush=True)
    return X


def training_year(source, cfg, rng, n_hours=HOURS_PER_YEAR):
    """Healthy reference year (no events). Alternate days -> fit / calibration (disjoint)."""
    T = temperature_profile(n_hours, rng)
    day = np.arange(n_hours) // 24
    fit = day % 2 == 0
    Xf = generate_features(source, cfg, T[fit], np.zeros(fit.sum(), int), [[]] * fit.sum(), rng, "fit")
    Xc = generate_features(source, cfg, T[~fit], np.zeros((~fit).sum(), int), [[]] * (~fit).sum(), rng, "cal")
    return Xf, T[fit], Xc, T[~fit]


def severity_set(source, cfg, rng, n_per_class=400, split="sev_train"):
    X, T, y = [], [], []
    temps = rng.uniform(-5, 25, 2 * n_per_class)
    k = 0
    for level in (1, 2):
        for _ in range(n_per_class):
            if split == "sev_train":
                a = source.severity_training_window(level, rng, temps[k])
            else:
                a = (source.severity_training_window(level, rng, temps[k]) if hasattr(source, "DAMAGE_LOSS")
                     else source.window(temps[k], level, rng, split=split))
            X.append(window_features(a, cfg)); T.append(temps[k]); y.append(level); k += 1
    return np.array(X), np.array(T), np.array(y)
