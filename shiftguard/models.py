"""Healthy-behaviour models: predict each sensor from the OTHER sensors + temperature.

Two interchangeable implementations with the same API:
  * MaskedSensorNet  – self-supervised masked-sensor modelling (one shared neural network,
                       trained by randomly hiding one sensor and reconstructing it).
  * RidgeCrossSensor – one linear model per sensor (fast, transparent baseline / fallback).

The residual of sensor i  =  what sensor i reports  -  what the rest of the structure says it
should report. Sensor faults break one sensor's agreement; damage breaks the agreement of a
whole region of the structure; temperature is explained away by the conditioning input.
"""
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler


def temperature_basis(T, use=True):
    T = np.asarray(T, dtype=float).reshape(-1)
    if not use:
        return np.zeros((len(T), 4))
    c = np.maximum(-T, 0)                           # freezing branch
    return np.stack([T / 10, (T / 10) ** 2, c / 5, (c / 5) ** 2], 1)


class _Base:
    def __init__(self, cfg):
        self.cfg = cfg
        self.N, self.B = cfg.n_sensors, cfg.n_bands
        self.sigma = None

    def predict_sensor(self, X, T, i):
        raise NotImplementedError

    def residuals(self, X, T):
        """(n, N, B) standardised residuals."""
        R = np.stack([X[:, i] - self.predict_sensor(X, T, i) for i in range(self.N)], 1)
        return R / self.sigma[None]

    def sensor_scores(self, X, T):
        """(n, N) mean squared standardised residual per sensor."""
        return (self.residuals(X, T) ** 2).mean(2)

    def _set_sigma(self, X, T):
        R = np.stack([X[:, i] - self.predict_sensor(X, T, i) for i in range(self.N)], 1)
        self.sigma = R.std(0) + 1e-6


class RidgeCrossSensor(_Base):
    def fit(self, X, T):
        self.models = []
        for i in range(self.N):
            self.models.append(Ridge(alpha=1.0).fit(self._z(X, T, i), X[:, i]))
        self._set_sigma(X, T)
        return self

    def _z(self, X, T, i):
        others = np.delete(X, i, axis=1).reshape(len(X), -1)
        return np.hstack([others, temperature_basis(T, self.cfg.use_temperature)])

    def predict_sensor(self, X, T, i):
        return self.models[i].predict(self._z(X, T, i))


class MaskedSensorNet(_Base):
    """Input = [all sensors with sensor i masked (zeros) | one-hot(i) | temperature basis]
       Output = sensor i's spectrum.   One network serves every sensor."""

    def fit(self, X, T, rng=None):
        rng = rng if rng is not None else np.random.default_rng(self.cfg.seed)
        n = len(X)
        self.mu = X.mean(0)
        self.sd = X.std(0) + 1e-6
        Xs = (X - self.mu) / self.sd
        inp, out = [], []
        for i in range(self.N):                     # every window x every masked sensor
            inp.append(self._z(Xs, T, i))
            out.append(Xs[:, i])
        inp, out = np.vstack(inp), np.vstack(out)
        perm = rng.permutation(len(inp))
        self.net = MLPRegressor(hidden_layer_sizes=self.cfg.mlp_hidden, activation="relu",
                                alpha=1e-3, learning_rate_init=1e-3, batch_size=256,
                                max_iter=self.cfg.mlp_max_iter, early_stopping=True,
                                n_iter_no_change=8, random_state=self.cfg.seed)
        self.net.fit(inp[perm], out[perm])
        self._set_sigma(X, T)
        return self

    def _z(self, Xs, T, i):
        m = Xs.copy()
        m[:, i] = 0.0
        oh = np.zeros((len(Xs), self.N)); oh[:, i] = 1
        return np.hstack([m.reshape(len(Xs), -1), oh, temperature_basis(T, self.cfg.use_temperature)])

    def predict_sensor(self, X, T, i):
        Xs = (X - self.mu) / self.sd
        return self.net.predict(self._z(Xs, T, i)) * self.sd[i] + self.mu[i]


def make_model(cfg):
    return {"mlp": MaskedSensorNet, "ridge": RidgeCrossSensor}[cfg.model](cfg)
