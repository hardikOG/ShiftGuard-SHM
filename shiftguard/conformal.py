"""Conformal p-values, p-to-e calibrators and e-detectors (conformal test martingales).

Why not per-window conformal prediction?  A per-window guarantee like "<= 5 % false positives"
still means ~440 false alarms per year at one window per hour. Here the evidence is
ACCUMULATED over time and the guarantee is about the whole monitoring run:

  CUSUM-type e-detector (Shin, Ramdas & Rinaldo, 2022), driven by conformal p-values
  (Vovk et al., 2021):      M_t = e_t * max(M_{t-1}, 1),     alarm when M_t >= c
  If the structure is unchanged (p-values ~ U(0,1), independent), E[time to false alarm] >= c.
"""
import numpy as np


class ConformalPValue:
    """Smoothed (randomised) inductive conformal p-value, upper tail: large score = strange."""

    def __init__(self, cal_scores, rng=None):
        self.cal = np.sort(np.asarray(cal_scores, dtype=float))
        self.n = len(self.cal)
        self.rng = rng if rng is not None else np.random.default_rng(0)

    def __call__(self, s):
        s = np.atleast_1d(np.asarray(s, dtype=float))
        gt = self.n - np.searchsorted(self.cal, s, side="right")
        eq = np.searchsorted(self.cal, s, side="right") - np.searchsorted(self.cal, s, side="left")
        u = self.rng.uniform(size=s.shape)
        return (gt + u * (eq + 1)) / (self.n + 1)


class LocalConformalPValue:
    """Temperature-localised conformal p-value: the test score is ranked only against the k
    calibration windows recorded at the most similar temperatures. This removes the
    temperature-dependence of the score (the model is less accurate when the deck is frozen),
    making p-values ~ U(0,1) conditionally on temperature (a Mondrian / localised conformal
    scheme for the benign covariate shift 'season')."""

    def __init__(self, cal_scores, cal_T, k=400, rng=None):
        o = np.argsort(cal_T)
        self.T = np.asarray(cal_T, float)[o]
        self.s = np.asarray(cal_scores, float)[o]
        self.k = min(int(k), len(self.T))
        self.rng = rng if rng is not None else np.random.default_rng(0)

    def __call__(self, s, T):
        s = np.atleast_1d(np.asarray(s, float)); T = np.atleast_1d(np.asarray(T, float))
        out = np.empty(len(s))
        for n, (si, Ti) in enumerate(zip(s, T)):
            c = np.searchsorted(self.T, Ti)
            lo = int(np.clip(c - self.k // 2, 0, len(self.T) - self.k))
            ref = self.s[lo:lo + self.k]
            gt = (ref > si).sum(); eq = (ref == si).sum()
            out[n] = (gt + self.rng.uniform() * (eq + 1)) / (self.k + 1)
        return out


def mixture_evalue(p, eps_grid=(0.05, 0.1, 0.2, 0.3, 0.5)):
    """Average of power calibrators  e = eps * p^(eps-1);  E[e] = 1 when p ~ U(0,1)."""
    p = np.atleast_1d(p)[:, None]
    eps = np.asarray(eps_grid)[None, :]
    return (eps * p ** (eps - 1)).mean(1)


class EDetector:
    """Online CUSUM e-detector with a cap so it can recover after a condition ends."""

    def __init__(self, level, cap):
        self.level, self.cap = level, cap
        self.m = 1.0

    def reset(self):
        self.m = 1.0

    def update(self, e):
        self.m = float(min(e * max(self.m, 1.0), self.cap))
        return self.m

    @property
    def alarm(self):
        return self.m >= self.level
