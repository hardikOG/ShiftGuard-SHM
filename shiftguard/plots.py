"""Paper figures. One colour per entity, used identically in every figure:
environment = blue, sensor fault = orange, structure / damage = red."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C_ENV, C_FAULT, C_DMG, C_BASE = "#2a78d6", "#eb6834", "#d03b3b", "#52514e"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def _event_spans(ax, truth, d):
    cols = {"env": C_ENV, "fault": C_FAULT, "damage": C_DMG}
    labs = np.array([str(t) for t in truth])
    for key in sorted(set(labs) - {"healthy"}):
        m = np.where(labs == key)[0]
        col = cols[key.split("-")[0]]
        ax.axvspan(d[m[0]], d[m[-1]] + 1 / 24, color=col, alpha=0.10, lw=0)


def _event_names(ax, truth, d):
    labs = np.array([str(t) for t in truth])
    nice = lambda k: (k.replace("env-coldsnap", "cold snap").replace("damage-", "damage ")
                      .replace("fault-s", "S").replace("-", " "))
    for key in sorted(set(labs) - {"healthy"}, key=lambda k: np.where(labs == k)[0][0]):
        m = np.where(labs == key)[0]
        ax.text(d[m[0]], 0.98, " " + nice(key), transform=ax.get_xaxis_transform(), rotation=90,
                va="top", ha="left", fontsize=7, color=INK2)


def timeline(pack, path):
    out, truth, T = pack["out"], pack["truth"], pack["T"]
    d = np.arange(len(T)) / 24
    level = pack["cfg"]["alarm_level"]
    fig, ax = plt.subplots(4, 1, figsize=(12, 9), sharex=True,
                           gridspec_kw=dict(height_ratios=[1.0, 0.55, 1.5, 0.9]))
    for a in ax:
        _event_spans(a, truth, d)
    ax[0].plot(d, T, lw=0.6, color=INK2)
    ax[0].set_ylabel("Air temperature (°C)")
    ax[0].set_title("Monitored year: weather, injected IoT sensor faults and progressive damage")
    _event_names(ax[0], truth, d)

    b = pack["base5"]
    ax[1].vlines(d[b], 0, 1, color=C_BASE, lw=0.5)
    ax[1].set_yticks([]); ax[1].grid(False)
    nfa = int((b & (truth == "healthy")).sum())
    ax[1].set_title(f"Baseline: per-window autoencoder score + 5 % conformal threshold — {nfa} false-alarm hours, every alarm reads 'damage'",
                    fontsize=8.5, fontweight="normal", color=INK2)

    ms = np.array([o["evidence_struct"] for o in out])
    mse = np.array([max(o["evidence_sensors"]) for o in out]) / len(out[0]["evidence_sensors"])
    me = np.array([o["evidence_env"] for o in out])
    for y, c, lab in [(me, C_ENV, "Environment"), (mse, C_FAULT, "Sensors (max, ÷N)"), (ms, C_DMG, "Structure")]:
        ax[2].semilogy(d, np.maximum(y, 1e-2), lw=0.8, color=c, label=lab)
    ax[2].axhline(level, ls="--", lw=0.8, color=INK)
    ax[2].text(d[-1], level * 1.4, f"alarm threshold: E[time to false alarm] ≥ {level:,.0f} h ", ha="right", fontsize=7.5)
    ax[2].set_ylim(1e-2, level * 30)
    ax[2].set_ylabel("Accumulated evidence\n(e-detector, log)")
    ax[2].legend(loc="upper left", ncol=3, fontsize=8, frameon=False)
    ax[2].set_title("ShiftGuard: three conformal e-detectors running in parallel", fontsize=9)

    rows = {"ENVIRONMENT": (1, C_ENV), "SENSOR_FAULT": (2, C_FAULT), "STRUCTURAL_DAMAGE": (3, C_DMG)}
    lab = np.array([o["label"] for o in out])
    for k, (yv, c) in rows.items():
        m = lab == k
        ax[3].vlines(d[m], yv - 0.38, yv + 0.38, color=c, lw=0.7)
    ax[3].set_yticks([1, 2, 3]); ax[3].set_yticklabels(["Environment", "Sensor fault", "Structural damage"])
    ax[3].set_ylim(0.4, 3.6); ax[3].set_xlabel("Day of monitored year")
    ax[3].set_title("ShiftGuard alarm attribution", fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def attribution_matrix(packs, path):
    groups = ["healthy", "environment", "sensor fault", "damage"]
    preds = ["NORMAL", "ENVIRONMENT", "SENSOR_FAULT", "STRUCTURAL_DAMAGE"]
    M = np.zeros((4, 4))
    for p in packs:
        for o, t in zip(p["out"], p["truth"]):
            t = str(t)
            g = "healthy" if t == "healthy" else "environment" if t.startswith("env") else \
                "sensor fault" if t.startswith("fault") else "damage"
            M[groups.index(g), preds.index(o["label"])] += 1
    R = M / M.sum(1, keepdims=True).clip(1)
    fig, ax = plt.subplots(figsize=(6.2, 4.4))
    ax.imshow(R, cmap="Blues", vmin=0, vmax=1)
    ax.grid(False)
    for i in range(4):
        for j in range(4):
            ax.text(j, i, f"{100 * R[i, j]:.1f}%", ha="center", va="center", fontsize=9,
                    color="white" if R[i, j] > 0.6 else INK)
    ax.set_xticks(range(4)); ax.set_xticklabels(["Normal", "Environment", "Sensor fault", "Damage"])
    ax.set_yticks(range(4)); ax.set_yticklabels(["Healthy", "Cold snap", "Sensor fault", "Damage"])
    ax.set_xlabel("ShiftGuard output (per hour)"); ax.set_ylabel("Ground truth")
    ax.set_title("Alarm attribution (row-normalised)")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def ablation(packs, path):
    keys = [k for k in packs[0]["results"] if k != "severity_stage"]
    short = {k: k.replace("Ablation: ", "– ").replace("ShiftGuard (proposed)", "ShiftGuard (full)") for k in keys}
    fa = [np.mean([p["results"][k]["false_alarm_episodes"] for p in packs]) for k in keys]
    fm = [np.mean([p["results"][k].get("fault_correct_attribution") or 0 for p in packs]) * 100 for k in keys]
    dl = [np.mean([p["results"][k]["damage_detection_delay_h"] if p["results"][k]["damage_detection_delay_h"] is not None else np.nan for p in packs]) for k in keys]
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8), sharey=True)
    y = np.arange(len(keys))[::-1]
    for a, vals, title, fmtv in [(ax[0], fa, "False-alarm episodes, healthy hours (lower = better)", "{:.0f}"),
                                 (ax[1], dl, "Damage detection delay, h (lower = better)", "{:.0f}"),
                                 (ax[2], fm, "Faults blamed on the right sensor, % (higher = better)", "{:.0f}")]:
        cols = [C_DMG if k.startswith("ShiftGuard") else "#9b9a95" for k in keys]
        v = np.nan_to_num(np.array(vals, float), nan=0)
        a.barh(y, v, color=cols, height=0.6)
        for yi, val, raw in zip(y, v, vals):
            a.text(val, yi, " " + ("missed" if np.isnan(raw) else fmtv.format(raw)), va="center", fontsize=8)
        a.set_title(title, fontsize=8.5); a.grid(axis="y", visible=False); a.set_axisbelow(True)
        a.set_xlim(0, max(v.max() * 1.25, 1))
    ax[0].set_yticks(y); ax[0].set_yticklabels([short[k] for k in keys], fontsize=8)
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def localisation(packs, path, damaged=(5, 6)):
    loc = np.mean([p["loc"] for p in packs], 0)
    fig, ax = plt.subplots(figsize=(6, 3.2))
    x = np.arange(1, len(loc) + 1)
    ax.bar(x, loc, color=[C_DMG if i in damaged else "#9b9a95" for i in x], width=0.6)
    ax.set_xticks(x); ax.set_xticklabels([f"S{i}" for i in x])
    ax.set_ylabel("Mean residual score"); ax.grid(axis="x", visible=False)
    ax.set_title("Damage localisation: residual per sensor during severe damage")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)
