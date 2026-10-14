"""Train the ShiftGuard monitor on one healthy year and save it for the live demo.

  python scripts/train_monitor.py                      # virtual bridge, masked-sensor MLP
  python scripts/train_monitor.py --model ridge        # faster
  python scripts/train_monitor.py --source z24 --z24-dir data/z24
"""
import argparse, os, pickle, sys, time
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shiftguard import Config
from shiftguard.sources import make_source
from shiftguard.scenario import training_year, severity_set
from shiftguard.monitor import ShiftGuard
from shiftguard.baselines import PerWindowAE

ap = argparse.ArgumentParser()
ap.add_argument("--source", default="sim", choices=["sim", "z24"])
ap.add_argument("--z24-dir", default=None)
ap.add_argument("--z24-setup", default="0")
ap.add_argument("--z24-channels", type=int, nargs="+", default=None)
ap.add_argument("--model", default="mlp", choices=["mlp", "ridge"])
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="models")
args = ap.parse_args()

t0 = time.time()
cfg = Config(model=args.model, seed=args.seed)
rng = np.random.default_rng(args.seed)
setup = args.z24_setup if args.z24_setup == "all" else int(args.z24_setup)
src = make_source(cfg, args.source, args.z24_dir, setup, args.z24_channels)
print(f"1/3 generating one healthy year of windows from {src.name} ...", flush=True)
Xf, Tf, Xc, Tc = training_year(src, cfg, rng)
print(f"2/3 training masked-sensor model ({args.model}) + conformal calibration ...", flush=True)
sg = ShiftGuard(cfg).fit(Xf, Tf, Xc, Tc)
print("3/3 training severity stage + baseline ...", flush=True)
Xs, Ts, ys = severity_set(src, cfg, rng, 400, "sev_train")
Xs2, Ts2, ys2 = severity_set(src, cfg, rng, 200, "sev_cal")
sg.fit_severity(Xs, Ts, ys, Xs2, Ts2, ys2)
base = PerWindowAE(seed=args.seed).fit(Xf, Xc)
os.makedirs(args.out, exist_ok=True)
path = os.path.join(args.out, f"shiftguard_{args.source}_{args.model}.pkl")
with open(path, "wb") as f:
    pickle.dump(dict(monitor=sg, baseline=base, cfg=cfg, source=args.source), f)
print(f"saved {path}  ({time.time() - t0:.0f}s)")
