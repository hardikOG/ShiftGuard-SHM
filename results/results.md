# ShiftGuard-SHM results (mlp model, source=sim, seeds=[0, 1, 2])

Healthy training year -> monitored year with a cold snap, 5 injected IoT sensor faults (drift, noise, dropout, spikes, clipping) and progressive damage (moderate -> severe). One window per hour; values averaged over seeds.

| Method | False-alarm h | False-alarm episodes | Damage delay (h) | Damage recall | Faults correctly attributed | Faults called damage | Cold snap called damage |
|---|---|---|---|---|---|---|---|
| ShiftGuard (proposed) | 26 | 7.7 | 3.7 | 98.7% | 93.6% | 0.0% | 0.0% |
| Per-window AE + conformal 5% | 347 | 314.7 | 4 | 67.6% | 0.0% | 86.1% | 36.1% |
| Per-window AE + conformal 0.1% | 7.7 | 3 | 326.3 | 43.8% | 0.0% | 70.3% | 17.3% |
| Ablation: per-window conformal 5% (no e-detector) | 351 | 328 | 0 | 86.7% | 0.0% | 9.2% | 31.9% |
| Ablation: no sensor masking | 40.7 | 7.3 | 3.7 | 98.7% | 3.4% | 90.9% | 0.2% |
| Ablation: global (not temperature-localised) calibration | 106 | 16.7 | 7 | 98.3% | 93.9% | 0.0% | 6.3% |
| Ablation: no temperature conditioning | 28.7 | 9.3 | 4.7 | 98.6% | 93.8% | 0.1% | 0.0% |
| Ablation: no environment monitor | 26.7 | 7.7 | 4 | 99.5% | 93.5% | 0.0% | 33.5% |

## Severity stage (conformal prediction sets, after a damage alarm)

- empirical coverage: 100.0% (target 90%)
- average set size: 1.00
- top-1 accuracy: 100.0%

## Validity check: healthy-only year (no events at all)

- ShiftGuard alarm episodes per year: 3.33 (28.7 alarm-hours)
- Per-window 5% baseline alarm episodes per year: 390.3 (444 alarm-hours)
- Design guarantee: E[time to first false alarm] >= 10000 windows (= 1.14 years at 1 window/hour)

## Damage localisation

Mean per-sensor residual during severe damage (virtual bridge damage is between sensors 5 and 6):

| S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---|---|---|---|---|---|---|
| 4.06 | 6.12 | 4.35 | 9.18 | 11.02 | 8.23 | 8.28 | 5.39 |

Figures: `figures/timeline.png`, `figures/attribution_matrix.png`, `figures/ablation.png`, `figures/localisation.png`
