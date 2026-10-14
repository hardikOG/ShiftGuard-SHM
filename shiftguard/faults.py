"""IoT sensor-fault injector.

Software-only sensing is turned into a methodological strength: because faults are injected,
every alarm has exact ground truth (which is impossible with a physical deployment).
Fault models follow the common SHM sensor-fault taxonomy (gain, drift, noise, spikes,
dropout / stuck, clipping / saturation).
"""
import numpy as np

FAULT_KINDS = ("gain", "drift", "noise", "spikes", "dropout", "clipping")


def inject(window, sensor, kind, rng, severity=1.0, progress=1.0):
    """Return a copy of `window` (channels, samples) with a fault on channel `sensor` (0-based).

    progress: elapsed fraction/days for time-evolving faults (drift grows with progress).
    severity: scales the fault strength.
    """
    a = window.copy()
    x = a[sensor]
    sd = x.std() + 1e-12
    if kind == "gain":
        a[sensor] = x * (1 + 0.5 * severity)
    elif kind == "drift":                           # slowly growing calibration (gain) drift
        a[sensor] = x * (1 + 0.04 * severity * progress)
    elif kind == "noise":                           # loose connector / EMI
        a[sensor] = x + rng.standard_normal(x.size) * 0.6 * severity * sd
    elif kind == "spikes":                          # intermittent impulses (packet corruption)
        n = max(1, int(0.004 * x.size * severity))
        idx = rng.choice(x.size, n, replace=False)
        y = x.copy(); y[idx] += rng.choice([-1, 1], n) * 15 * sd
        a[sensor] = y
    elif kind == "dropout":                         # node offline / stuck at constant
        a[sensor] = rng.standard_normal(x.size) * 1e-3 * sd
    elif kind == "clipping":                        # MEMS saturation
        lim = (0.6 / severity) * sd
        a[sensor] = np.clip(x, -lim, lim)
    else:
        raise ValueError(f"unknown fault kind {kind!r}; choose from {FAULT_KINDS}")
    return a
