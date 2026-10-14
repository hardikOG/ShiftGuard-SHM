"""Baselines the paper compares against.

PerWindowAE: autoencoder-style anomaly score (PCA reconstruction error on all features, the
linear equivalent of the original Autoencoder) + per-window split-conformal threshold.
This is the old pipeline's alarm logic: each window is judged on its own.
"""
import numpy as np
from sklearn.decomposition import PCA

from .conformal import ConformalPValue


class PerWindowAE:
    def __init__(self, n_components=10, seed=0):
        self.k = n_components
        self.rng = np.random.default_rng(seed)

    def fit(self, X_fit, X_cal):
        F = X_fit.reshape(len(X_fit), -1)
        self.mu, self.sd = F.mean(0), F.std(0) + 1e-6
        self.pca = PCA(self.k).fit((F - self.mu) / self.sd)
        self.p = ConformalPValue(self.score(X_cal), self.rng)
        return self

    def score(self, X):
        z = (X.reshape(len(X), -1) - self.mu) / self.sd
        return ((z - self.pca.inverse_transform(self.pca.transform(z))) ** 2).mean(1)

    def alarms(self, X, alpha):
        return self.p(self.score(X)) < alpha


def per_window_alarms(p_values, alpha):
    return np.asarray(p_values) < alpha
