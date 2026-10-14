"""Check the processed Z24 files before using them.

  python scripts/inspect_z24.py --z24-dir data/z24

Prints shapes, the label distribution, and tests the assumed row order
(scenario x setup x segment = 17 x 9 x 10): rows of the same setup should look more alike
(same sensor layout) than rows of different setups.
"""
import argparse, os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shiftguard.sources import Z24_SCENARIOS, Z24_DEFAULT_CLASSES

ap = argparse.ArgumentParser()
ap.add_argument("--z24-dir", required=True)
args = ap.parse_args()
X = np.load(os.path.join(args.z24_dir, "inputs.npy"), mmap_mode="r")
y = np.load(os.path.join(args.z24_dir, "labels.npy")).ravel()
print("inputs:", X.shape, X.dtype, "| labels:", y.shape, y.dtype)
vals, cnt = np.unique(y, return_counts=True)
off = 1 if vals.min() == 0 else 0
print("\nlabel -> scenario (count):")
for v, c in zip(vals, cnt):
    s = int(v) + off
    cls = [k for k, ss in Z24_DEFAULT_CLASSES.items() if s in ss]
    print(f"  {v:>3} -> scenario {s:>2} {Z24_SCENARIOS.get(s, '?'):32s} rows={c:4d} class={cls[0] if cls else 'excluded'}")

# per-row signature: relative RMS of each channel (depends on the sensor layout)
n = min(len(X), 400)
idx = np.linspace(0, len(X) - 1, n).astype(int)
sig = np.stack([np.log(np.asarray(X[i]).std(1) + 1e-12) for i in idx])
sig -= sig.mean(1, keepdims=True)
setup = (idx // 10) % 9
d = np.linalg.norm(sig[:, None] - sig[None], axis=2)
same = d[setup[:, None] == setup[None]].mean()
diff = d[setup[:, None] != setup[None]].mean()
print(f"\nrow-order check: mean signature distance same-setup={same:.3f}, different-setup={diff:.3f}")
print("  -> order assumption looks RIGHT (use --z24-setup 0..8)" if same < 0.7 * diff else
      "  -> order assumption looks WRONG: use --z24-setup all, or edit Z24Source for your file's row order")
