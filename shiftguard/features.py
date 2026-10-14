"""Window -> per-sensor log band-power spectrum (n_sensors x n_bands)."""
import numpy as np
from scipy.signal import welch


def band_edges(cfg):
    return np.linspace(cfg.band_lo, cfg.band_hi, cfg.n_bands + 1)


def window_features(a, cfg):
    """a: (n_sensors, win) raw acceleration -> (n_sensors, n_bands).

    The excitation level (traffic/wind) is removed by subtracting the MEDIAN over sensors of
    each sensor's mean log power: a single faulty sensor cannot shift everyone else's features.
    """
    f, P = welch(a, fs=cfg.fs, nperseg=cfg.nperseg, axis=1)
    edges = band_edges(cfg)
    bp = np.stack([P[:, (f >= lo) & (f < hi)].mean(1) for lo, hi in zip(edges[:-1], edges[1:])], 1)
    L = np.log(bp + 1e-20)
    return L - np.median(L.mean(1))


def batch_features(windows, cfg):
    return np.stack([window_features(w, cfg) for w in windows])
