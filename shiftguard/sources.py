"""Data sources that produce raw multichannel acceleration windows.

Both sources expose the same method:
    window(T, damage_level, rng, split) -> ndarray (n_sensors, win)
damage_level: 0 = healthy, 1 = moderate, 2 = severe.
split: 'fit' | 'cal' | 'stream' | 'sev_train' | 'sev_cal'  (keeps training and test data disjoint)
"""
import os
import numpy as np
from scipy.linalg import eigh

from .environment import stiffness_factor, temperature_warp


# ----------------------------------------------------------------------------------------
# 1) Virtual bridge: 8-DOF fixed-fixed chain, first mode ~4 Hz (similar to Z24 ~3.9 Hz)
# ----------------------------------------------------------------------------------------
class VirtualBridge:
    DAMAGE_LOSS = {0: 0.0, 1: 0.10, 2: 0.25}      # stiffness loss per severity class

    def __init__(self, cfg, damage_element=5, k0=5240.0, zeta=0.02):
        self.cfg = cfg
        self.N = cfg.n_sensors
        self.k0, self.zeta = k0, zeta
        self.damage_element = damage_element       # element between sensor 5 and 6 (1-based)
        self.freqs = np.fft.rfftfreq(cfg.win, 1 / cfg.fs)
        self.om = 2 * np.pi * self.freqs
        self.name = "virtual-bridge"

    def _modal(self, k_elem):
        N = self.N
        K = np.zeros((N, N))
        for e, k in enumerate(k_elem):
            i, j = e - 1, e
            if i >= 0:
                K[i, i] += k
            if j < N:
                K[j, j] += k
            if i >= 0 and j < N:
                K[i, j] -= k
                K[j, i] -= k
        w2, phi = eigh(K)
        return np.sqrt(w2), phi

    def window(self, T, damage_level=0, rng=None, split="stream", damage_element=None, loss=None):
        rng = rng if rng is not None else np.random.default_rng()
        N = self.N
        k = np.full(N + 1, self.k0) * stiffness_factor(T)
        elem = self.damage_element if damage_element is None else damage_element
        k[elem] *= 1 - (self.DAMAGE_LOSS[int(damage_level)] if loss is None else loss)
        wn, phi = self._modal(k)
        amp = np.exp(rng.normal(0, 0.5))            # traffic / wind excitation level varies
        F = (rng.standard_normal((N, len(self.freqs))) + 1j * rng.standard_normal((N, len(self.freqs)))) * amp
        q = (phi.T @ F) / (wn[:, None] ** 2 - self.om[None, :] ** 2 + 2j * self.zeta * wn[:, None] * self.om[None, :])
        A = -(self.om[None, :] ** 2) * (phi @ q)
        return np.fft.irfft(A, n=self.cfg.win, axis=1) / 50.0

    def severity_training_window(self, level, rng, T):
        """Labelled damage examples for the severity stage, at RANDOM locations (as an FE model
        or lab test would provide) so the test damage location is never seen in training."""
        elem = int(rng.integers(1, self.N))
        return self.window(T, level, rng, damage_element=elem)


# ----------------------------------------------------------------------------------------
# 2) Z24 bridge (KU Leuven progressive damage test), processed HuggingFace version:
#    huggingface.co/datasets/thanglexuan/Z24-dataset-processed
#    inputs.npy (1530, 27, 6000) float64, labels.npy (1530,)
# ----------------------------------------------------------------------------------------
Z24_SCENARIOS = {
    1: "first reference", 2: "settlement system installed", 3: "pier lowered 20 mm",
    4: "pier lowered 40 mm", 5: "pier lowered 80 mm", 6: "pier lowered 95 mm",
    7: "pier lifted / foundation tilt", 8: "new reference", 9: "concrete spalling 12 m2",
    10: "concrete spalling 24 m2", 11: "landslide at abutment", 12: "concrete hinge failure",
    13: "2 anchor heads failed", 14: "4 anchor heads failed", 15: "2 of 16 tendons ruptured",
    16: "4 of 16 tendons ruptured", 17: "6 of 16 tendons ruptured",
}
# Same 3-class grouping as the project deck (Healthy / Moderate / Severe)
Z24_DEFAULT_CLASSES = {
    0: [1, 2],
    1: [3, 4, 5, 6, 7, 9, 10, 11],
    2: [12, 13, 14, 15, 16, 17],
}


class Z24Source:
    """Replays Z24 recordings as virtual IoT sensor windows.

    Z24 has 9 sensor setups (different sensor layouts). The cross-sensor model needs a fixed
    layout, so one setup is used at a time. By default rows are assumed to be ordered
    (scenario, setup, segment) = 17 x 9 x 10; run scripts/inspect_z24.py to verify, or pass
    setup='all' to use every row.
    """

    def __init__(self, cfg, data_dir, setup=0, channels=None, classes=None, rows_per_setup=10,
                 n_setups=9):
        self.cfg = cfg
        self.name = f"z24-setup{setup}"
        X = np.load(os.path.join(data_dir, "inputs.npy"), mmap_mode="r")
        y = np.load(os.path.join(data_dir, "labels.npy")).astype(int).ravel()
        if y.min() == 0:
            y = y + 1                                # 0-based -> scenario numbers 1..17
        self.labels = y
        n = len(y)
        if setup == "all":
            keep = np.ones(n, bool)
        else:
            setup_of_row = (np.arange(n) // rows_per_setup) % n_setups
            keep = setup_of_row == int(setup)
        channels = list(range(cfg.n_sensors)) if channels is None else list(channels)
        if len(channels) != cfg.n_sensors:
            raise ValueError("len(channels) must equal cfg.n_sensors")
        classes = classes or Z24_DEFAULT_CLASSES
        cls_of_scen = {s: c for c, ss in classes.items() for s in ss}
        self.pools = {}                              # (class, split) -> list of (channels, samples)
        rng = np.random.default_rng(cfg.seed)
        for c in (0, 1, 2):
            rows = [i for i in np.where(keep)[0] if cls_of_scen.get(int(y[i])) == c]
            if not rows:
                raise ValueError(f"no Z24 rows for class {c}; check labels / --setup / class map")
            rows = list(rng.permutation(rows))
            segs = [np.asarray(X[i][channels], dtype=np.float64) for i in rows]
            segs = [s / (s.std() + 1e-12) for s in segs]
            if c == 0:   # healthy: fit 50 %, cal 25 %, stream 25 %
                a, b = int(0.5 * len(segs)), int(0.75 * len(segs))
                self.pools[(0, "fit")], self.pools[(0, "cal")], self.pools[(0, "stream")] = segs[:a], segs[a:b], segs[b:]
            else:        # damage: severity-train 40 %, severity-cal 20 %, stream 40 %
                a, b = int(0.4 * len(segs)), int(0.6 * len(segs))
                self.pools[(c, "sev_train")], self.pools[(c, "sev_cal")], self.pools[(c, "stream")] = segs[:a], segs[a:b], segs[b:]
        for k, v in self.pools.items():
            if len(v) == 0:
                raise ValueError(f"empty Z24 pool {k}: too few rows for this setup; try setup='all'")

    def window(self, T, damage_level=0, rng=None, split="stream"):
        rng = rng if rng is not None else np.random.default_rng()
        split = {"fit": "fit", "cal": "cal"}.get(split, split)
        key = (int(damage_level), split)
        if key not in self.pools:                   # e.g. healthy windows requested for sev_* splits
            key = (int(damage_level), "stream")
        pool = self.pools[key]
        seg = pool[rng.integers(len(pool))]
        w = temperature_warp(seg, T, self.cfg.win, rng)
        return w * np.exp(rng.normal(0, 0.5))       # varying excitation level

    def severity_training_window(self, level, rng, T):
        return self.window(T, level, rng, split="sev_train")


def make_source(cfg, name, z24_dir=None, z24_setup=0):
    if name == "sim":
        return VirtualBridge(cfg)
    if name == "z24":
        if not z24_dir:
            raise ValueError("--z24-dir is required for the z24 source")
        return Z24Source(cfg, z24_dir, setup=z24_setup)
    raise ValueError(name)
