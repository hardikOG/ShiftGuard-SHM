# ShiftGuard-SHM results (ridge model, source=z24, seeds=[0, 1, 2])

Healthy training year -> monitored year with a cold snap, 5 injected IoT sensor faults (drift, noise, dropout, spikes, clipping) and progressive damage (moderate -> severe). One window per hour; values averaged over seeds.

| Method | False-alarm h | False-alarm episodes | Damage delay (h) | Damage recall | Faults correctly attributed | Faults called damage | Cold snap called damage |
|---|---|---|---|---|---|---|---|
| ShiftGuard (proposed) | 10.3 | 5.3 | 494 | 23.5% | 46.5% | 0.3% | 0.0% |
| Per-window AE + conformal 5% | 391.3 | 362.7 | 70.7 | 10.4% | 0.0% | 23.0% | 16.5% |
| Per-window AE + conformal 0.1% | 12.7 | 12.3 | 94.3 | 1.5% | 0.0% | 12.6% | 2.4% |
| Ablation: per-window conformal 5% (no e-detector) | 367.3 | 343.3 | 68 | 16.0% | 0.0% | 8.6% | 9.7% |
| Ablation: no sensor masking | 16.7 | 7 | 37 | 30.6% | 4.8% | 41.8% | 0.0% |
| Ablation: global (not temperature-localised) calibration | 11.7 | 6.7 | 493.3 | 23.6% | 45.7% | 2.0% | 0.0% |
| Ablation: no temperature conditioning | 10.3 | 5.3 | 494.3 | 23.3% | 46.2% | 0.3% | 0.0% |
| Ablation: no environment monitor | 10.7 | 5.7 | 492.7 | 25.4% | 47.9% | 0.3% | 3.0% |

## Severity stage (conformal prediction sets, after a damage alarm)

- empirical coverage: 92.4% (target 90%)
- average set size: 1.46
- top-1 accuracy: 76.6%

## Validity check: healthy-only year (no events at all)

- ShiftGuard alarm episodes per year: 0.33 (0.3 alarm-hours)
- Per-window 5% baseline alarm episodes per year: 462.3 (500 alarm-hours)
- Design guarantee: E[time to first false alarm] >= 10000 windows (= 1.14 years at 1 window/hour)

## Damage localisation

Mean per-sensor residual during severe damage (virtual bridge damage is between sensors 5 and 6):

| S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---|---|---|---|---|---|---|
| 12.52 | 5.66 | 13.78 | 11.43 | 10.89 | 7.21 | 11.76 | 10.22 |

Figures: `figures/timeline.png`, `figures/attribution_matrix.png`, `figures/ablation.png`, `figures/localisation.png`
