"""End-to-end offline experiment: train on a healthy year, monitor a test year with
injected faults / cold snap / progressive damage, compare with baselines and ablations,
and write paper-ready tables + figures.

  python scripts/run_experiment.py                         # virtual bridge, MLP model
  python scripts/run_experiment.py --model ridge --quick   # fast check (~1 min)
  python scripts/run_experiment.py --source z24 --z24-dir data/z24 --z24-setup 0
"""
import argparse, copy, dataclasses, json, os, pickle, sys, time
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shiftguard import Config
from shiftguard.sources import make_source
from shiftguard.scenario import (HOURS_PER_YEAR, build_timeline, generate_features, load_events,
                                 severity_set, training_year)
from shiftguard.monitor import ShiftGuard, NORMAL, ENV, FAULT, DAMAGE
from shiftguard.baselines import PerWindowAE, per_window_alarms
from shiftguard import plots


def truth_group(t):
    if t == "healthy": return "healthy"
    if t.startswith("env"): return "environment"
    if t.startswith("fault"): return "sensor fault"
    return "damage"


def episodes(mask):
    mask = np.asarray(mask, bool)
    return int(mask[0]) + int(((mask[1:].astype(int) - mask[:-1].astype(int)) == 1).sum())


def evaluate(labels, fault_sensors, truth, onset_hour):
    """Hour-level metrics for one alarm/attribution sequence."""
    labels = np.asarray(labels, dtype=object)
    healthy = truth == "healthy"
    alarm = labels != NORMAL
    res = dict(false_alarm_hours=int((alarm & healthy).sum()),
               false_alarm_episodes=episodes(alarm & healthy),
               healthy_hours=int(healthy.sum()))
    dm = np.where(labels[onset_hour:] == DAMAGE)[0]
    res["damage_detection_delay_h"] = int(dm[0]) if len(dm) else None
    dmask = np.array([str(t).startswith("damage") for t in truth])
    res["damage_recall"] = float((labels[dmask] == DAMAGE).mean()) if dmask.any() else None
    # fault attribution: correct class AND correct sensor
    fm = np.array([str(t).startswith("fault") for t in truth])
    if fm.any():
        ok = []
        for t in np.where(fm)[0]:
            s = int(str(truth[t]).split("-")[1][1:])
            ok.append(labels[t] == FAULT and fault_sensors[t] == s)
        res["fault_correct_attribution"] = float(np.mean(ok))
        res["fault_misread_as_damage"] = float((labels[fm] == DAMAGE).mean())
    em = np.array([str(t).startswith("env") for t in truth])
    if em.any():
        res["coldsnap_misread_as_damage"] = float((labels[em] == DAMAGE).mean())
    return res


def run_once(args, seed, outdir, verbose=True):
    cfg = Config(model=args.model, seed=seed, alarm_level=args.alarm_level)
    rng = np.random.default_rng(seed)
    src = make_source(cfg, args.source, args.z24_dir, args.z24_setup)
    hours = 24 * 120 if args.quick else HOURS_PER_YEAR
    t0 = time.time()
    if verbose: print(f"[seed {seed}] 1/6 generating healthy training year ({src.name}) ...", flush=True)
    Xf, Tf, Xc, Tc = training_year(src, cfg, rng, n_hours=hours)

    if verbose: print(f"[seed {seed}] 2/6 generating monitoring year with events ...", flush=True)
    events = load_events(args.events)
    if args.quick:   # compress the default schedule into 120 days
        scale = 120 / 366
        events = [dict(e, start_day=e["start_day"] * scale, end_day=e["end_day"] * scale) for e in events]
    T2, D2, F2, Y2 = build_timeline(hours, rng, events)
    X2 = generate_features(src, cfg, T2, D2, F2, rng, "stream")
    onset = int(min(e["start_day"] for e in events if e["type"] == "damage") * 24)

    if verbose: print(f"[seed {seed}] 3/6 training ShiftGuard ({cfg.model}) + severity stage + baseline ...", flush=True)
    sg = ShiftGuard(cfg).fit(Xf, Tf, Xc, Tc)
    Xs, Ts, ys = severity_set(src, cfg, rng, 150 if args.quick else 400, "sev_train")
    Xs2, Ts2, ys2 = severity_set(src, cfg, rng, 100 if args.quick else 200, "sev_cal")
    sg.fit_severity(Xs, Ts, ys, Xs2, Ts2, ys2)
    base = PerWindowAE(seed=seed).fit(Xf, Xc)

    if verbose: print(f"[seed {seed}] 4/6 monitoring ...", flush=True)
    out, sc = sg.run(X2, T2)
    labels = [o["label"] for o in out]
    fs = [o["fault_sensor"] for o in out]
    results = {"ShiftGuard (proposed)": evaluate(labels, fs, Y2, onset)}

    for name, alpha in [("Per-window AE + conformal 5%", 0.05), ("Per-window AE + conformal 0.1%", 0.001)]:
        al = base.alarms(X2, alpha)
        results[name] = evaluate(np.where(al, DAMAGE, NORMAL), [None] * len(al), Y2, onset)

    if verbose: print(f"[seed {seed}] 5/6 ablations ...", flush=True)
    # A: same ShiftGuard scores, but per-window conformal decision (no evidence accumulation)
    pg = sg.p_struct(sc["G"], T2)
    al = per_window_alarms(pg, 0.05)
    results["Ablation: per-window conformal 5% (no e-detector)"] = evaluate(np.where(al, DAMAGE, NORMAL), [None] * len(al), Y2, onset)
    ablations = [("Ablation: no sensor masking", dict(use_masking=False)),
                 ("Ablation: global (not temperature-localised) calibration", dict(local_k=0)),
                 ("Ablation: no temperature conditioning", dict(use_temperature=False)),
                 ("Ablation: no environment monitor", dict(use_env_monitor=False))]
    for name, change in ablations:
        cfg_a = dataclasses.replace(cfg, **change)
        if "use_temperature" in change:
            sga = ShiftGuard(cfg_a).fit(Xf, Tf, Xc, Tc)
        else:
            sga = copy.copy(sg); sga.cfg = cfg_a
            sga.calibrate(Xc, Tc)
        oa, _ = sga.run(X2, T2)
        results[name] = evaluate([o["label"] for o in oa], [o["fault_sensor"] for o in oa], Y2, onset)

    # severity stage on damage hours that were alarmed
    dmask = np.array([o["label"] == DAMAGE and str(y).startswith("damage") for o, y in zip(out, Y2)])
    if dmask.any():
        true = np.array([1 if str(y) == "damage-moderate" else 2 for y in Y2[dmask]])
        names = {1: "Moderate", 2: "Severe"}
        sets = [o["severity_set"] for o, m in zip(out, dmask) if m]
        tops = [o["severity"] for o, m in zip(out, dmask) if m]
        results["severity_stage"] = dict(
            coverage=float(np.mean([names[t] in s for t, s in zip(true, sets)])),
            target_coverage=1 - cfg.severity_alpha,
            avg_set_size=float(np.mean([len(s) for s in sets])),
            top1_accuracy=float(np.mean([names[t] == p for t, p in zip(true, tops)])))

    # damage localisation (mean per-sensor residual during severe damage)
    sev = np.array([str(y) == "damage-severe" for y in Y2])
    loc = sc["S"][sev].mean(0) if sev.any() else np.zeros(cfg.n_sensors)

    if verbose: print(f"[seed {seed}] 6/6 null check: healthy-only year (validity of the guarantee) ...", flush=True)
    null = None
    if not args.no_null:
        Tn, Dn, Fn, Yn = build_timeline(hours, rng, [])
        Xn = generate_features(src, cfg, Tn, Dn, Fn, rng, "stream")
        on, _ = sg.run(Xn, Tn)
        ln = np.array([o["label"] for o in on])
        an = base.alarms(Xn, 0.05)
        null = dict(hours=len(ln), shiftguard_alarm_hours=int((ln != NORMAL).sum()),
                    shiftguard_alarm_episodes=episodes(ln != NORMAL),
                    baseline5_alarm_hours=int(an.sum()), baseline5_alarm_episodes=episodes(an),
                    guarantee=f"E[time to first false alarm] >= {cfg.alarm_level:.0f} windows")

    pack = dict(cfg=cfg.__dict__, out=out, T=T2, truth=Y2, base5=base.alarms(X2, 0.05),
                loc=loc, results=results, null=null, onset=onset, elapsed=time.time() - t0)
    if seed == args.seeds[0]:
        os.makedirs(os.path.join(outdir, "..", "models"), exist_ok=True)
        model_path = os.path.join(outdir, "..", "models", f"shiftguard_{args.source}_{args.model}.pkl")
        with open(model_path, "wb") as f:
            pickle.dump(dict(monitor=sg, baseline=base, cfg=cfg, source=args.source), f)
        if verbose: print(f"    saved trained monitor -> {os.path.normpath(model_path)}")
    return pack


PCT_COLS = {"damage_recall", "fault_correct_attribution", "fault_misread_as_damage", "coldsnap_misread_as_damage"}


def fmt(v, col):
    if v is None: return "-"
    if col in PCT_COLS: return f"{100 * v:.1f}%"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}"


def write_report(packs, outdir, args):
    keys = [k for k in packs[0]["results"] if k != "severity_stage"]
    cols = ["false_alarm_hours", "false_alarm_episodes", "damage_detection_delay_h", "damage_recall",
            "fault_correct_attribution", "fault_misread_as_damage", "coldsnap_misread_as_damage"]
    head = ["Method", "False-alarm h", "False-alarm episodes", "Damage delay (h)", "Damage recall",
            "Faults correctly attributed", "Faults called damage", "Cold snap called damage"]
    agg = {}
    for k in keys:
        agg[k] = {}
        for c in cols:
            vals = [p["results"][k].get(c) for p in packs]
            vals = [v for v in vals if v is not None]
            agg[k][c] = float(np.mean(vals)) if vals else None
    lines = [f"# ShiftGuard-SHM results ({packs[0]['cfg']['model']} model, source={args.source}, seeds={args.seeds})", "",
             "Healthy training year -> monitored year with a cold snap, 5 injected IoT sensor faults "
             "(drift, noise, dropout, spikes, clipping) and progressive damage (moderate -> severe). "
             "One window per hour; values averaged over seeds.", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for k in keys:
        row = [k] + [fmt(agg[k][c], c) for c in cols]
        lines.append("| " + " | ".join(row) + " |")
    sv = [p["results"].get("severity_stage") for p in packs if p["results"].get("severity_stage")]
    if sv:
        lines += ["", "## Severity stage (conformal prediction sets, after a damage alarm)", "",
                  f"- empirical coverage: {100*np.mean([s['coverage'] for s in sv]):.1f}% (target {100*sv[0]['target_coverage']:.0f}%)",
                  f"- average set size: {np.mean([s['avg_set_size'] for s in sv]):.2f}",
                  f"- top-1 accuracy: {100*np.mean([s['top1_accuracy'] for s in sv]):.1f}%"]
    nl = [p["null"] for p in packs if p["null"]]
    if nl:
        lines += ["", "## Validity check: healthy-only year (no events at all)", "",
                  f"- ShiftGuard alarm episodes per year: {np.mean([n['shiftguard_alarm_episodes'] for n in nl]):.2f} "
                  f"({np.mean([n['shiftguard_alarm_hours'] for n in nl]):.1f} alarm-hours)",
                  f"- Per-window 5% baseline alarm episodes per year: {np.mean([n['baseline5_alarm_episodes'] for n in nl]):.1f} "
                  f"({np.mean([n['baseline5_alarm_hours'] for n in nl]):.0f} alarm-hours)",
                  f"- Design guarantee: {nl[0]['guarantee']} (= {packs[0]['cfg']['alarm_level']/8760:.2f} years at 1 window/hour)"]
    loc = np.mean([p["loc"] for p in packs], 0)
    lines += ["", "## Damage localisation", "",
              "Mean per-sensor residual during severe damage (virtual bridge damage is between sensors 5 and 6):", "",
              "| " + " | ".join(f"S{i+1}" for i in range(len(loc))) + " |", "|" + "---|" * len(loc),
              "| " + " | ".join(f"{v:.2f}" for v in loc) + " |"]
    lines += ["", "Figures: `figures/timeline.png`, `figures/attribution_matrix.png`, `figures/ablation.png`, `figures/localisation.png`"]
    with open(os.path.join(outdir, "results.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(outdir, "results.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(aggregate=agg, per_seed=[dict(seed=s, results=p["results"], null=p["null"]) for s, p in zip(args.seeds, packs)]),
                  f, indent=1, default=str)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="sim", choices=["sim", "z24"])
    ap.add_argument("--z24-dir", default=None)
    ap.add_argument("--z24-setup", default="0")
    ap.add_argument("--model", default="mlp", choices=["mlp", "ridge"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--alarm-level", type=float, default=1e4)
    ap.add_argument("--events", default=None, help="JSON file with custom events (see scenario.DEFAULT_EVENTS)")
    ap.add_argument("--quick", action="store_true", help="120-day years for a fast check")
    ap.add_argument("--no-null", action="store_true", help="skip the healthy-only validity year")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    if args.z24_setup != "all":
        args.z24_setup = int(args.z24_setup)
    os.makedirs(os.path.join(args.out, "figures"), exist_ok=True)
    packs = [run_once(args, s, args.out) for s in args.seeds]
    report = write_report(packs, args.out, args)
    plots.timeline(packs[0], os.path.join(args.out, "figures", "timeline.png"))
    plots.attribution_matrix(packs, os.path.join(args.out, "figures", "attribution_matrix.png"))
    plots.ablation(packs, os.path.join(args.out, "figures", "ablation.png"))
    plots.localisation(packs, os.path.join(args.out, "figures", "localisation.png"))
    print("\n" + report)
    print(f"\nDone in {sum(p['elapsed'] for p in packs):.0f}s -> {args.out}/results.md, {args.out}/figures/")


if __name__ == "__main__":
    main()
