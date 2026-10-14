"""Environmental model: temperature profiles and the temperature effect on structural stiffness.

Z24 is the classic example: below 0 degC the asphalt layer freezes and the bridge's natural
frequencies jump by >10 %. Ignoring this is the #1 cause of false damage alarms in SHM.
"""
import numpy as np


def stiffness_factor(T):
    """Relative stiffness vs. temperature (1.0 at 10 degC), bilinear with freezing stiffening."""
    T = np.asarray(T, dtype=float)
    f = 1 + 0.004 * (10 - T)
    return f + np.where(T < 0, 0.02 * (-T), 0.0)


def temperature_profile(n_hours, rng, mean=9.0, seasonal=13.0, daily=4.0, start_hour=0):
    """Hourly air temperature: seasonal + daily cycle + AR(1) weather noise."""
    h = np.arange(start_hour, start_hour + n_hours)
    d = h / 24.0
    T = mean + seasonal * np.sin(2 * np.pi * (d - 110) / 365) + daily * np.sin(2 * np.pi * (h % 24 - 9) / 24)
    noise = np.zeros(n_hours)
    e = rng.standard_normal(n_hours) * 0.6
    for t in range(1, n_hours):
        noise[t] = 0.97 * noise[t - 1] + e[t]
    return T + noise


def apply_coldsnap(T, start_day, end_day, delta):
    """Add a smooth cold (delta<0) or heat (delta>0) wave between two days."""
    T = T.copy()
    d = np.arange(len(T)) / 24.0
    m = (d >= start_day) & (d < end_day)
    T[m] += delta * np.sin(np.pi * (d[m] - start_day) / (end_day - start_day))
    return T


def temperature_warp(signal_long, T, out_len, rng, T_ref=10.0):
    """Impose the temperature effect on a *recorded* multichannel signal (used for Z24).

    Stiffness k -> k*s shifts every natural frequency by sqrt(s). Playing the signal back
    sqrt(s) times faster shifts its spectrum by the same factor:  y(t) = x(r t),  r = sqrt(s/s_ref).
    signal_long: (channels, L_long) with L_long >= out_len * r_max.
    """
    r = float(np.sqrt(stiffness_factor(T) / stiffness_factor(T_ref)))
    need = int(np.ceil(out_len * r)) + 2
    L = signal_long.shape[1]
    if need > L:
        raise ValueError("segment too short for temperature warp")
    off = rng.integers(0, L - need + 1)
    t_in = np.arange(need)
    t_out = np.arange(out_len) * r
    seg = signal_long[:, off:off + need]
    return np.stack([np.interp(t_out, t_in, ch) for ch in seg])
