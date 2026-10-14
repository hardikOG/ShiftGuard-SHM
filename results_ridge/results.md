# ShiftGuard-SHM results (ridge model, source=sim, seeds=[0, 1, 2])

Healthy training year -> monitored year with a cold snap, 5 injected IoT sensor faults (drift, noise, dropout, spikes, clipping) and progressive damage (moderate -> severe). One window per hour; values averaged over seeds.

| Method | False-alarm h | False-alarm episodes | Damage delay (h) | Damage recall | Faults correctly attributed | Faults called damage | Cold snap called damage |
|---|---|---|---|---|---|---|---|
| ShiftGuard (proposed) | 34.7 | 8 | 2.7 | 98.8% | 95.7% | 1.2% | 0.0% |
| Per-window AE + conformal 5% | 347 | 314.7 | 4 | 67.6% | 0.0% | 86.1% | 36.1% |
| Per-window AE + conformal 0.1% | 7.7 | 3 | 326.3 | 43.8% | 0.0% | 70.3% | 17.3% |
| Ablation: per-window conformal 5% (no e-detector) | 377 | 349.7 | 0 | 96.3% | 0.0% | 18.3% | 30.8% |
| Ablation: no sensor masking | 36.3 | 8.3 | 2.3 | 98.8% | 1.0% | 96.4% | 0.0% |
| Ablation: global (not temperature-localised) calibration | 91 | 16 | 7.3 | 98.3% | 97.2% | 0.1% | 0.6% |
| Ablation: no temperature conditioning | 38 | 8 | 2.7 | 98.8% | 95.7% | 1.3% | 0.0% |
| Ablation: no environment monitor | 35.7 | 8.3 | 3 | 99.6% | 94.9% | 2.0% | 33.3% |

## Severity stage (conformal prediction sets, after a damage alarm)

- empirical coverage: 99.7% (target 90%)
- average set size: 1.00
- top-1 accuracy: 99.7%

## Validity check: healthy-only year (no events at all)

- ShiftGuard alarm episodes per year: 2.67 (24.0 alarm-hours)
- Per-window 5% baseline alarm episodes per year: 390.3 (444 alarm-hours)
- Design guarantee: E[time to first false alarm] >= 10000 windows (= 1.14 years at 1 window/hour)

## Damage localisation

Mean per-sensor residual during severe damage (virtual bridge damage is between sensors 5 and 6):

| S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---|---|---|---|---|---|---|
| 1.60 | 1.95 | 4.42 | 9.32 | 23.67 | 24.10 | 5.46 | 4.61 |

Figures: `figures/timeline.png`, `figures/attribution_matrix.png`, `figures/ablation.png`, `figures/localisation.png`
