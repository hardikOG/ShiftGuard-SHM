# ShiftGuard-SHM results (mlp model, source=z24, seeds=[0, 1, 2])

Healthy training year -> monitored year with a cold snap, 5 injected IoT sensor faults (drift, noise, dropout, spikes, clipping) and progressive damage (moderate -> severe). One window per hour; values averaged over seeds.

| Method | False-alarm h | False-alarm episodes | Damage delay (h) | Damage recall | Faults correctly attributed | Faults called damage | Cold snap called damage |
|---|---|---|---|---|---|---|---|
| ShiftGuard (proposed) | 12.7 | 5.7 | 494 | 27.3% | 44.7% | 0.0% | 0.0% |
| Per-window AE + conformal 5% | 391.3 | 362.7 | 70.7 | 10.4% | 0.0% | 23.0% | 16.5% |
| Per-window AE + conformal 0.1% | 12.7 | 12.3 | 94.3 | 1.5% | 0.0% | 12.6% | 2.4% |
| Ablation: per-window conformal 5% (no e-detector) | 421 | 385.3 | 123.3 | 18.3% | 0.0% | 10.1% | 15.3% |
| Ablation: no sensor masking | 19 | 8 | 374 | 28.6% | 9.9% | 36.1% | 0.0% |
| Ablation: global (not temperature-localised) calibration | 20.3 | 9 | 492 | 27.9% | 45.1% | 0.7% | 0.0% |
| Ablation: no temperature conditioning | 8.7 | 5 | 469.3 | 27.6% | 43.4% | 0.7% | 0.0% |
| Ablation: no environment monitor | 11.3 | 5.3 | 492.7 | 29.1% | 45.7% | 0.4% | 7.1% |

## Severity stage (conformal prediction sets, after a damage alarm)

- empirical coverage: 90.4% (target 90%)
- average set size: 1.46
- top-1 accuracy: 69.3%

## Validity check: healthy-only year (no events at all)

- ShiftGuard alarm episodes per year: 2.67 (6.3 alarm-hours)
- Per-window 5% baseline alarm episodes per year: 462.3 (500 alarm-hours)
- Design guarantee: E[time to first false alarm] >= 10000 windows (= 1.14 years at 1 window/hour)

## Damage localisation

Mean per-sensor residual during severe damage (virtual bridge damage is between sensors 5 and 6):

| S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---|---|---|---|---|---|---|
| 15.69 | 18.38 | 35.02 | 29.54 | 18.03 | 18.58 | 16.75 | 16.52 |

Figures: `figures/timeline.png`, `figures/attribution_matrix.png`, `figures/ablation.png`, `figures/localisation.png`
