"""ShiftGuard monitor: masked-sensor residuals -> conformal e-detectors -> attribution.

Three families of detectors run in parallel on every window:
  * STRUCTURE   – residual of the structure after the most suspicious sensor is masked and
                  re-imputed (robust to any single faulty sensor)
  * SENSOR i    – disagreement of sensor i with the rest of the network (one per sensor)
  * ENVIRONMENT – is the current temperature inside the envelope seen during training?

Attribution rule (per window):
  ENVIRONMENT        if an alarm fires while conditions are outside experience
  STRUCTURAL_DAMAGE  if the structure detector alarms (sensor faults already masked out)
  SENSOR_FAULT (i)   if only sensor detectors alarm
  NORMAL             otherwise
"""
import numpy as np
from sklearn.linear_model import LogisticRegression

from .conformal import ConformalPValue, LocalConformalPValue, EDetector, mixture_evalue
from .models import make_model

NORMAL, ENV, FAULT, DAMAGE = "NORMAL", "ENVIRONMENT", "SENSOR_FAULT", "STRUCTURAL_DAMAGE"
SEVERITY_NAMES = {1: "Moderate", 2: "Severe"}


class SeverityConformal:
    """Stage 2 (only after a STRUCTURAL_DAMAGE alarm): Moderate vs Severe with split-conformal
    prediction sets, e.g. {Severe} or {Moderate, Severe} with >= 1-alpha coverage."""

    def __init__(self, alpha=0.1):
        self.alpha = alpha

    @staticmethod
    def _f(S):
        return np.log(S + 1e-9)

    def fit(self, S_tr, y_tr, S_cal, y_cal):
        self.clf = LogisticRegression(max_iter=2000).fit(self._f(S_tr), y_tr)
        P = self.clf.predict_proba(self._f(S_cal))
        idx = np.searchsorted(self.clf.classes_, y_cal)
        nc = 1 - P[np.arange(len(y_cal)), idx]
        n = len(nc)
        q = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
        self.qhat = np.quantile(nc, q, method="higher")
        return self

    def predict(self, S):
        P = self.clf.predict_proba(self._f(np.atleast_2d(S)))
        top = self.clf.classes_[P.argmax(1)]
        sets = [[int(c) for c, p in zip(self.clf.classes_, row) if 1 - p <= self.qhat] or [int(t)]
                for row, t in zip(P, top)]            # never return an empty set
        return top, sets


class ShiftGuard:
    def __init__(self, cfg):
        self.cfg = cfg
        self.N = cfg.n_sensors
        self.model = make_model(cfg)
        self.severity = None
        self.rng = np.random.default_rng(cfg.seed + 1)

    # ------------------------------------------------------------------ scoring
    def masked_global(self, X, T, S):
        """Global structure score after masking + imputing the worst sensor of each window."""
        J = S.argmax(1)
        if not self.cfg.use_masking:
            s = np.sort(S, 1)
            return s[:, :-1].mean(1), J
        G = np.zeros(len(X))
        for j in range(self.N):
            sel = J == j
            if not sel.any():
                continue
            Xm = X[sel].copy()
            Xm[:, j] = self.model.predict_sensor(Xm, T[sel], j)
            Sm = np.delete(self.model.sensor_scores(Xm, T[sel]), j, axis=1)
            G[sel] = Sm.mean(1)
        return G, J

    def env_score(self, T):
        T = np.atleast_1d(T)
        d = np.sort(np.abs(T[:, None] - self.T_ref[None, :]), 1)
        return d[:, :self.cfg.env_k].mean(1)

    def score_batch(self, X, T):
        T = np.asarray(T, dtype=float)
        S = self.model.sensor_scores(X, T)
        G, J = self.masked_global(X, T, S)
        return dict(S=S, G=G, J=J, E=self.env_score(T))

    # ------------------------------------------------------------------ training
    def fit(self, X_fit, T_fit, X_cal, T_cal):
        self.model.fit(X_fit, T_fit)
        return self.calibrate(X_cal, T_cal)

    def calibrate(self, X_cal, T_cal):
        """Conformal calibration on held-out healthy windows (no model training)."""
        self.T_ref = np.sort(np.asarray(T_cal, float))
        sc = self.score_batch(X_cal, T_cal)
        T_cal = np.asarray(T_cal, float)
        if self.cfg.local_k:
            self._p_struct = LocalConformalPValue(sc["G"], T_cal, self.cfg.local_k, self.rng)
            self._p_sensor = [LocalConformalPValue(sc["S"][:, i], T_cal, self.cfg.local_k, self.rng) for i in range(self.N)]
        else:
            g = ConformalPValue(sc["G"], self.rng)
            self._p_struct = lambda s, T: g(s)
            self._p_sensor = []
            for i in range(self.N):
                pi = ConformalPValue(sc["S"][:, i], self.rng)
                self._p_sensor.append(lambda s, T, pi=pi: pi(s))
        sub = self.T_ref[::max(1, len(self.T_ref) // 1500)]
        d = np.sort(np.abs(sub[:, None] - self.T_ref[None, :]), 1)[:, 1:self.cfg.env_k + 1].mean(1)
        self.p_env = ConformalPValue(d, self.rng)
        self.cal_scores = sc
        self.reset()
        return self

    def fit_severity(self, X_tr, T_tr, y_tr, X_cal, T_cal, y_cal):
        S_tr = self.model.sensor_scores(X_tr, T_tr)
        S_ca = self.model.sensor_scores(X_cal, T_cal)
        self.severity = SeverityConformal(self.cfg.severity_alpha).fit(S_tr, y_tr, S_ca, y_cal)
        return self

    # ------------------------------------------------------------------ online monitoring
    def reset(self):
        c = self.cfg
        self.det_struct = EDetector(c.alarm_level, c.cap)
        self.det_sensor = [EDetector(c.alarm_level * self.N, c.cap * self.N) for _ in range(self.N)]
        self.det_env = EDetector(c.alarm_level, c.cap)
        self.t = 0

    def p_struct(self, G, T):
        return self._p_struct(G, T)

    def _update(self, S, G, J, E, T):
        c = self.cfg
        p_g = float(self._p_struct(G, T)[0])
        m_g = self.det_struct.update(mixture_evalue(p_g, c.eps_grid)[0])
        m_s = [d.update(mixture_evalue(float(p(S[i], T)[0]), c.eps_grid)[0])
               for i, (d, p) in enumerate(zip(self.det_sensor, self._p_sensor))]
        m_e = self.det_env.update(mixture_evalue(float(self.p_env(E)[0]), c.eps_grid)[0]) if c.use_env_monitor else 0.0
        s_alarm = [d.alarm for d in self.det_sensor]
        env_novel = c.use_env_monitor and self.det_env.alarm
        label, fault_sensor = NORMAL, None
        if env_novel and (self.det_struct.alarm or any(s_alarm)):
            label = ENV
        elif self.det_struct.alarm:
            label = DAMAGE
        elif s_alarm[J]:
            label, fault_sensor = FAULT, int(J) + 1
        elif any(s_alarm):
            label, fault_sensor = FAULT, int(np.argmax([m if a else -1 for m, a in zip(m_s, s_alarm)])) + 1
        lvl = np.log10(c.alarm_level)
        health = float(100 * (1 - np.clip(np.log10(max(m_g, 1.0)) / lvl, 0, 1)))
        out = dict(t=self.t, label=label, fault_sensor=fault_sensor,
                   evidence_struct=m_g, evidence_sensors=m_s, evidence_env=m_e,
                   env_novel=bool(env_novel), p_struct=p_g, health_score=health,
                   sensor_scores=[float(v) for v in S], global_score=float(G),
                   damage_location=[int(i) + 1 for i in np.argsort(-S)[:2]] if label == DAMAGE else None,
                   severity=None, severity_set=None)
        if label == DAMAGE and self.severity is not None:
            top, sets = self.severity.predict(S[None])
            out["severity"] = SEVERITY_NAMES.get(int(top[0]), str(top[0]))
            out["severity_set"] = [SEVERITY_NAMES.get(k, str(k)) for k in sets[0]]
        self.t += 1
        return out

    def step(self, x, T):
        """Online: x = (n_sensors, n_bands) features of one window, T = temperature."""
        sc = self.score_batch(x[None], np.array([T]))
        return self._update(sc["S"][0], sc["G"][0], sc["J"][0], sc["E"][0], T)

    def run(self, X, T):
        """Offline: score a whole stream in batch, then run the detectors sequentially."""
        self.reset()
        sc = self.score_batch(X, T)
        T = np.asarray(T, float)
        return [self._update(sc["S"][t], sc["G"][t], sc["J"][t], sc["E"][t], T[t]) for t in range(len(X))], sc
