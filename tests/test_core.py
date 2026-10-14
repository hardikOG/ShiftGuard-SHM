"""Sanity tests:  python -m pytest -q tests   (or: python tests/test_core.py)"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shiftguard.conformal import ConformalPValue, LocalConformalPValue, EDetector, mixture_evalue
from shiftguard.faults import inject, FAULT_KINDS
from shiftguard import Config


def test_pvalues_uniform_under_null():
    rng = np.random.default_rng(0)
    p = ConformalPValue(rng.normal(size=2000), rng)(rng.normal(size=20000))
    assert abs(p.mean() - 0.5) < 0.01 and abs((p < 0.05).mean() - 0.05) < 0.01


def test_local_pvalues_uniform_with_temperature_dependent_scores():
    rng = np.random.default_rng(1)
    Tc = rng.uniform(-10, 30, 4000); sc = rng.normal(size=4000) * (1 + (Tc < 0) * 2)
    Tt = rng.uniform(-10, 30, 5000); st = rng.normal(size=5000) * (1 + (Tt < 0) * 2)
    p = LocalConformalPValue(sc, Tc, 300, rng)(st, Tt)
    assert abs((p[Tt < 0] < 0.05).mean() - 0.05) < 0.02


def test_evalue_has_mean_one():
    import warnings
    from scipy.integrate import quad      # E[e(p)] = integral_0^1 e(p) dp must be exactly 1
    warnings.filterwarnings("ignore")
    val, _ = quad(lambda p: mixture_evalue(np.array([p]))[0], 0, 1, limit=200)
    assert abs(val - 1) < 1e-3


def test_edetector_rarely_alarms_under_null():
    rng = np.random.default_rng(3)
    alarms = 0
    for _ in range(20):
        d = EDetector(1e3, 1e4)
        e = mixture_evalue(rng.uniform(size=2000))
        alarms += any(d.update(x) >= 1e3 for x in e)
    assert alarms <= 3           # E[time to alarm] >= 1000 -> few alarms in 20 runs of 2000


def test_edetector_detects_shift_fast():
    rng = np.random.default_rng(4)
    d = EDetector(1e4, 1e5)
    e = mixture_evalue(rng.uniform(size=200) ** 4)      # small p-values after a change
    t = next(i for i, x in enumerate(e) if d.update(x) >= 1e4)
    assert t < 50


def test_fault_injection_changes_only_target_sensor():
    rng = np.random.default_rng(5)
    a = rng.normal(size=(8, 2048))
    for k in FAULT_KINDS:
        b = inject(a, 2, k, rng, progress=5)
        assert np.allclose(np.delete(b, 2, 0), np.delete(a, 2, 0))
        assert not np.allclose(b[2], a[2])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
