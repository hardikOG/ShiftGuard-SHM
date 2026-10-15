> **Superseded:** the submission version is `paper/latex/main.tex` (IEEE conference format, compiled to `paper/latex/main.pdf`). It adds the Kullaa (2011) related work, the measured c = 10^5 trade-off, the Z24 event-injection note, the sigma definition, the CPU spec and a code-availability statement.

# Damage, Weather, or a Broken Sensor? Anytime-Valid Alarm Attribution for Software-Defined AIoT Structural Health Monitoring

*Hardik Grover, Advait Anand, Akash Kumar, Yograj, [member 5] — Dept. of CTECH, SRM Institute of Science and Technology, Kattankulathur. Supervisor: Dr. P. Saravanan*

> Draft for Review-2. Results come from `results/results.md` and `results_ridge/results.md` (3 seeds),
> regenerated after the per-sensor detectors were switched to mask-and-impute scores (Section IV). Table III uses the
> real Z24 recordings (`results_z24_ridge/` and `results_z24/`).

---

## Abstract
Data-driven structural health monitoring (SHM) systems usually score each measurement window
independently and report every anomaly as possible damage. In a continuously running AIoT
deployment this design fails in two ways:
- **Per-window error rates become hundreds of false alarms per year.** Even a calibrated 5 % per-window
  rate means about 440 false alarms per year at one window per hour.
- **Alarms caused by environmental variation or by faulty IoT sensors cannot be told apart from real
  damage.**

We propose **ShiftGuard**, a monitoring framework with four components:
1. A self-supervised *masked-sensor model* predicts each sensor from the rest of the network and
   temperature.
2. A *mask-and-impute* step isolates any single faulty sensor and fills in lost packets.
3. *Temperature-localised conformal p-values* feed three families of *conformal e-detectors*
   (CUSUM-type test martingales): structure, per-sensor and environment.
4. A *conformal severity stage* reports damage severity as a prediction set.

The alarm comes with an anytime-style guarantee: the expected time to a false alarm is at least a chosen
threshold. Each alarm is attributed to structural damage, unprecedented environmental conditions or a
specific faulty sensor.

The sensing layer is fully software-defined: virtual MQTT sensor nodes replay a bridge model and the
Z24 benchmark, with a fault injector. This gives exact ground truth for sensor faults, which physical
deployments cannot provide.

Results:
- **False alarms:** over a simulated monitoring year with a record cold snap, five types of IoT sensor
  fault and progressive damage, ShiftGuard reduces false-alarm episodes from 315 to about 8 (and false-alarm hours
  from 347 to 26) compared with a per-window conformal autoencoder baseline.
- **Detection:** it detects moderate damage within 4 h in simulation. On real Z24 recordings it detects
  severe damage but misses the moderate stage (Section VI).
- **Sensor faults:** it attributes 94 % of sensor-fault hours to the correct sensor, and labels none of
  them as damage.
- **Cold snap:** it never labels the cold snap as damage.
- **Real data:** on the Z24 bridge recordings it keeps false alarms about 40× below the baseline
  (10 vs 391 hours).

**Index Terms**: structural health monitoring, AIoT, conformal prediction, test martingales, e-values,
sensor fault isolation, environmental variability, Z24 bridge.

---

## I. Introduction
- **Motivation:** bridges and buildings degrade silently, and manual inspection is periodic and subjective. IoT
  sensing combined with AI promises continuous monitoring.
- **Gap 1 (sequential guarantees):** SHM models report accuracy or F1, or at best a per-window
  calibrated error rate (conformal prediction). Monitoring is a *sequential* problem. With N windows per year,
  per-window guarantees compound into N·α false alarms, and operators stop trusting the system.
- **Gap 2 (attribution):** a deviation from the healthy baseline has three common causes:
  - structural damage
  - environmental and operational variation: for example, Z24's natural frequencies jump when the deck freezes
  - IoT sensor faults: drift, noise, dropout, spikes and saturation

  Prior work treats these separately. Temperature compensation and sensor-fault isolation (e.g.
  FS-LSTM, stacked-GRU frameworks) are separate pipelines, and none comes with a statistical alarm guarantee.
- **Gap 3 (validation):** physical deployments cannot provide ground truth for which sensor failed, or when.
- **Contributions:**
  1. A masked-sensor healthy-behaviour model whose residuals separate *local* inconsistency (a sensor
     fault) from *regional* inconsistency (damage). Its mask-and-impute step also repairs lost packets.
  2. The first use, to our knowledge, of *conformal e-detectors* (CUSUM-type conformal test martingales)
     for SHM alarms. The guarantee is on the expected time to a false alarm. Temperature-localised conformal
     calibration handles the seasonal covariate shift.
  3. A three-way attribution rule (damage / environment / sensor-i) plus conformal severity sets.
  4. A software-defined AIoT testbed: MQTT virtual nodes, edge monitor, dashboard, an interactive
     browser digital twin and Node-RED alerts, with a fault-injection protocol that gives exact ground truth.

## II. Related Work
*(Reuse the 11 papers from the Zeroth Review deck and add the following.)*
- **Deep SHM on Z24:**
  - WaveNet / MiniRocket at the edge (Dabbous et al., 2024)
  - TCN-GAT autoencoder (Ni et al., 2025)
  - GAN digital twin (Impraimakis & Palkanoglou, 2025)
  - foundation models / masked autoencoders for SHM (Benfenati et al., 2024)

  All of these use per-window decisions and no attribution.
- **Sensor fault vs damage:**
  - FS-LSTM-based isolation
  - stacked-GRU isolation in noisy environments
  - probabilistic sensor-fault detection in bridge SHM

  These are separate classifiers and assume normal environmental conditions.
- **Environmental variability:** temperature-effect removal by regression, PCA or cointegration before
  damage detection.
- **Conformal prediction:**
  - Angelopoulos & Bates (2023)
  - conformal test martingales for change-point detection (Vovk et al., 2021)
  - e-detectors (Shin, Ramdas & Rinaldo, 2022)
  - WATCH weighted-conformal monitoring of AI deployments (Prinster et al., ICML 2025)

  None of these has been applied to SHM.

## III. System Architecture (software-defined AIoT)
Fig. 1 should show the architecture diagram from the README.
1. **Virtual sensing layer:** 8 accelerometer nodes and 1 temperature node publish 20 s windows (100 Hz)
   over MQTT once per hour. The source is either an 8-DOF bridge model (first mode about 4 Hz, Z24-like
   stiffening below 0 °C) or Z24 recordings replayed with a temperature warp. A fault injector applies
   gain, drift, noise, spikes, dropout and clipping. A Wokwi ESP32 + DHT22 node can override the temperature.
2. **Edge analytics:** ShiftGuard (Section IV) reassembles each window from the MQTT packets, imputes lost
   packets and updates all ten detectors in a median of 4.9 ms per window (p95 9.6 ms) on a laptop CPU (measured over the live
   pipeline, ridge model, including feature extraction).
3. **Application layer:**
   - a SQLite store
   - a Streamlit dashboard
   - a browser digital twin connected to the broker over MQTT-over-WebSocket: the deck is animated from the
     live accelerometer windows, and faults, weather and damage are injected by clicking on the model
   - a Node-RED flow: damage and sensor-fault alerts (including a severity escalation) are emailed;
     weather alerts only go to the log
4. **Fault tolerance:**
   - crashed components are restarted by a supervisor, and the edge monitor resumes its store
   - every MQTT client reconnects with back-off and re-subscribes
   - windows are processed in strict sequence order, with late packets imputed
   - a restarted sensor network is detected and appended to the history

   These behaviours are covered by an automated multi-process test (20 % packet loss and a sensor-network
   restart).

## IV. Methodology
**Features.** Each window gives, for each sensor $i$, a vector of $B=16$ log band powers $x_i\in\mathbb R^B$
(1–30 Hz, Welch). The excitation level is removed by subtracting the median over sensors of each sensor's
mean log power, so one faulty channel cannot shift the features of the others.

**Masked-sensor model.** A network $f_\theta$ is trained only on healthy data:
$\hat x_i = f_\theta(x_{-i}, e_i, \phi(T))$. Here $x_{-i}$ is the window with sensor $i$ masked,
$e_i$ is a one-hot sensor index and $\phi(T)$ is a temperature basis that includes a freezing branch.
Training randomly masks sensors (self-supervised). The sensor score is
$s_i = \frac1B\lVert (x_i-\hat x_i)/\sigma_i\rVert^2$.

**Mask-and-impute.** Let $j^*=\arg\max_i s_i$. Replace $x_{j^*}$ by $\hat x_{j^*}$, recompute the other
sensors' scores $s_i'$, and define the structure score $G=\operatorname{mean}_{i\neq j^*} s_i'$. A faulty
sensor then leaves $G$ unchanged, while damage raises it. The per-sensor detectors use the same masked
scores: $\tilde s_{j^*}=s_{j^*}$ and $\tilde s_i=s_i'$ for $i\neq j^*$. Without this, a faulty sensor also
inflates the residuals of the neighbours that are predicted from it. Their detectors then accumulate
evidence, and when the fault clears the alarm is passed on to a neighbour. Lost packets are imputed the
same way: features are computed from the received channels only, and each missing sensor is predicted
from the others.

**Temperature-localised conformal p-values.** For a score $s$ observed at temperature $T$, rank $s$ among
the $k=400$ calibration scores recorded at the temperatures closest to $T$:
$p = \frac{\#\{c>s\} + U(\#\{c=s\}+1)}{k+1}$. This removes the dependence of model error on temperature,
a benign covariate shift.

**Conformal e-detectors.** Each p-value becomes an e-value through a mixture of power calibrators,
$e=\frac1{|E|}\sum_{\varepsilon\in E}\varepsilon p^{\varepsilon-1}$, with $\mathbb E[e]=1$ under the null.
The detector state is updated as $M_t = e_t\max(M_{t-1},1)$ and raises an alarm when $M_t\ge c$. If the
p-values are i.i.d. uniform (no change), $\mathbb E[\tau_{\text{false}}]\ge c$. We use $c=10^4$ windows,
about 14 months at one window per hour. Three families run in parallel:
- structure ($G$)
- each sensor ($\tilde s_i$, with threshold $Nc$, which is a Bonferroni correction)
- environment (k-NN novelty of $T$ against the calibration temperatures)

The detector state is capped at $10c$ so that it recovers after a condition ends.

**Attribution.**
- **ENVIRONMENT:** an alarm fires while the environment detector is also in alarm. The conditions have
  never been seen before, so the alarm is held at low confidence.
- **STRUCTURAL DAMAGE:** otherwise, the structure detector is in alarm.
- **SENSOR FAULT $j$:** only a sensor detector is in alarm.

**Severity.** After a damage alarm, a logistic model on $\log s$ outputs a split-conformal prediction
set over {Moderate, Severe} with ≥ 90 % coverage. It is trained on damage at *random* locations, so the
test location is never seen in training.

## V. Experimental Setup
- **Data:**
  - one healthy training year: alternate days used for fitting and calibration
  - one monitored year containing:
    - a cold snap 9 °C below the seasonal profile (days 15–22)
    - drift on S3 (days 120–134)
    - noise on S6 (days 200–204)
    - dropout on S1 (days 260–262)
    - spikes on S4 (days 285–288)
    - clipping on S7 (days 300–303)
    - moderate damage (10 % stiffness loss, days 330–348), then severe damage (25 %, days 348–365)
  - one extra healthy-only year to check validity
  - 3 random seeds
- **Baselines:**
  - an autoencoder-style score (PCA reconstruction error on all features) with a per-window split-conformal
    threshold at α = 5 % and α = 0.1 %. This is the pipeline from our Zeroth Review.
  - the ShiftGuard score with a per-window conformal decision
- **Ablations:**
  - no masking
  - global (not localised) calibration
  - no temperature conditioning
  - no environment monitor
- **Metrics:**
  - false-alarm hours and episodes on healthy hours
  - damage detection delay and recall
  - fault hours attributed to the correct sensor
  - faults and cold-snap hours mislabelled as damage
  - severity-set coverage
  - empirical false-alarm rate on the healthy-only year

## VI. Results
**Table I.** Simulated monitoring year, masked-sensor neural model (MLP). Mean of 3 seeds.

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

**Table II.** The same experiment with the linear cross-sensor model (ridge).

| Method | False-alarm h | False-alarm episodes | Damage delay (h) | Damage recall | Faults correctly attributed | Faults called damage | Cold snap called damage |
|---|---|---|---|---|---|---|---|
| ShiftGuard (proposed) | 23.3 | 6.7 | 2.7 | 98.8% | 95.7% | 1.2% | 0.0% |
| Per-window AE + conformal 5% | 347 | 314.7 | 4 | 67.6% | 0.0% | 86.1% | 36.1% |
| Per-window AE + conformal 0.1% | 7.7 | 3 | 326.3 | 43.8% | 0.0% | 70.3% | 17.3% |
| Ablation: per-window conformal 5% (no e-detector) | 377 | 349.7 | 0 | 96.3% | 0.0% | 18.3% | 30.8% |
| Ablation: no sensor masking | 36.3 | 8.3 | 2.3 | 98.8% | 1.0% | 96.4% | 0.0% |
| Ablation: global (not temperature-localised) calibration | 64.3 | 13 | 7.3 | 98.3% | 97.3% | 0.1% | 0.6% |
| Ablation: no temperature conditioning | 26.3 | 7.7 | 2.7 | 98.8% | 95.7% | 1.3% | 0.0% |
| Ablation: no environment monitor | 24 | 7 | 3 | 99.6% | 94.9% | 2.0% | 33.3% |

**Validity (healthy-only year, 3 seeds).**
- ShiftGuard: 3.3 (MLP) and 2.7 (ridge) false-alarm episodes per year.
- Per-window 5 % baseline: 390 false-alarm episodes per year.
- The design target is E[time to false alarm] ≥ 1.14 years. Counting the per-sensor detectors (a union
  bound gives c/2 overall) and hourly autocorrelation, the realised rate is a few episodes per year.
  That is about 100× fewer than the baseline, but above the nominal bound. Report this honestly. Raising
  c to 10⁵ trades about 25 % longer detection delay for fewer alarms.

**Severity stage.** Conformal sets reach 100 % (MLP) and 99.7 % (ridge) coverage, against a 90 % target,
with an average set size of 1.0.

**Localisation.** During severe damage, the mean per-sensor residual peaks at S5–S6, where the damage
was placed:
- ridge: 23.7 and 24.1, against ≤ 9.3 elsewhere
- MLP: the peak is less sharp (S5 = 11.0, S4 = 9.2)

Key reading of the tables:
- **Accumulating evidence is what removes false alarms.** The per-window decision on the *same* score
  gives about 330–350 false-alarm episodes, against 7–8 for the e-detector.
- **Masking is what makes fault attribution possible.** Without it, 91–96 % of fault hours are called
  damage, against 0–1 % with masking.
- **Localised calibration cuts false-alarm hours by about 75 %** (106 → 26 h for MLP, 64 → 23 h for ridge)
  and halves detection delay.
- **The environment monitor is what stops the cold snap being called damage** (33 % → 0 %).
- **The baselines face a dilemma.** At α = 5 % the baseline detects damage fast but raises 315
  false-alarm episodes. At α = 0.1 % it misses moderate damage entirely, with a 326 h delay and 44 % recall.

Figures to include:
- **Fig. 2** (`timeline.png`) shows the baseline firing all year, while ShiftGuard attributes each event correctly.
- **Fig. 3** (`attribution_matrix.png`)
- **Fig. 4** (`ablation.png`)
- **Fig. 5** (`localisation.png`)

**Table III.** The same protocol on the real Z24 recordings (ridge model, mean of 3 seeds).

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

With the masked-sensor MLP instead of ridge (`results_z24/`, 3 seeds), ShiftGuard gives:

| ShiftGuard (MLP) | 12.7 | 5.7 | 494 | 27.3% | 44.7% | 0.0% | 0.0% |

That is 12.7 false-alarm hours, 27.3 % damage recall, and 2.67 false-alarm episodes in the healthy-only
year. The severity-set coverage is 90.4 %. The conclusions are the same as for ridge.

**Z24 setup.** The processed Z24 progressive-damage data has 1530 recordings
(17 scenarios × 9 sensor setups × 10 segments, 27 channels, 60 s at 100 Hz):
- Healthy: scenarios 1–2. Moderate damage: scenarios 3–7 and 9–11. Severe damage: scenarios 12–17.
  Scenario 8 (the new reference after settlement) is excluded.
- The cross-sensor model needs a fixed sensor layout. With a single setup there are only 20 healthy
  recordings, and calibration and test windows then come from different recordings, which breaks
  exchangeability: ShiftGuard raised 795 false-alarm hours in a 120-day pilot run.
- We therefore use the 8 channels whose RMS level is as stable *between* setups as *within* a setup
  (channels 1, 2, 3, 9, 13, 17, 18, 19). These behave like the fixed reference sensors of the Z24
  campaign, so all 180 healthy recordings can be used. The selection uses healthy recordings only.
- Healthy recordings are split 50 / 25 / 25 % into fitting, calibration and the monitored stream. Damaged
  recordings are split 40 / 20 / 40 % into severity training, severity calibration and the stream.

**Z24 reading.**
- **False alarms carry over from simulation to real data.** 10.3 false-alarm hours (5.3 episodes) against 391
  hours (363 episodes) for the per-window baseline. The healthy-only year gives 0.33 false-alarm episodes,
  against 462 for the baseline.
- **Weather and sensor faults are still not mistaken for damage.** 0.3 % of fault hours and 0 % of cold-snap
  hours are labelled damage, against 23 % and 16.5 % for the baseline.
- **Damage detection is the weak point on Z24.** Recall is 23.5 % and the first damage alarm comes after
  about 494 h. That is 62 h into the severe stage: **the moderate stage (pier settlement, spalling,
  landslide) is missed on these channels**. The baseline is no better (10.4 % recall at α = 5 %). The early
  Z24 damage scenarios change the response of the shared reference channels very little. Using the full
  setup-specific layouts, or modal features instead of band powers, is future work.
- **Fault attribution to the correct sensor drops to 46.5 %** (95.7 % in simulation), although faults are
  almost never called damage. Real recordings have weaker cross-sensor redundancy than the 8-DOF model,
  so a fault on one channel is more often blamed on a neighbour.
- **Severity sets** keep their coverage guarantee (92.4 % against a 90 % target) but are less sharp
  (average set size 1.46, against 1.0 in simulation).

## VII. Discussion and Limitations
- **Accumulating evidence is what removes false alarms.** The ablation that keeps ShiftGuard's score but
  decides window-by-window is about as noisy as the baseline.
- **Masking is what turns sensor faults from "damage" into correctly localised maintenance tickets.**
- **Temperature-localised calibration is what keeps the guarantee valid across seasons.**
- **The guarantee is approximate.** It assumes exchangeable healthy windows, and hourly windows are
  autocorrelated. The healthy-only year reports how much this matters in practice.
- **Single-fault assumption.** Mask-and-impute removes one sensor per window. Simultaneous faults would
  need an iterative version. (Lost packets are already imputed iteratively, for any number of missing
  sensors up to half the network.)
- **Simulated temperature effect.** The Z24 temperature effect is simulated (the progressive-damage test
  has no temperature channel). Long-term Z24 monitoring data would allow a fully measured evaluation.
- **Z24 damage sensitivity.** On the 8 shared reference channels, moderate Z24 damage is not detected
  (Table III). The alarm guarantee and the attribution of faults and weather hold on real data, but
  damage sensitivity depends on sensor placement and features.
- **Model choice.** The linear (ridge) variant localises damage more sharply. The neural variant is
  the self-supervised masked model. Both give the same alarm behaviour, so the framework is
  model-agnostic.

## VIII. Conclusion
ShiftGuard reframes SHM alarms as a sequential, attributable decision. It answers *what changed*: the
structure, the weather or a sensor. It also gives a statistical bound on how often it raises a false alarm.
The software-defined AIoT testbed makes this evaluation possible with exact ground truth.

## References (add to the existing 13)
14. V. Vovk, I. Petej, I. Nouretdinov, E. Ahlberg, L. Carlsson, A. Gammerman, "Retrain or not retrain: Conformal test martingales for change-point detection," *Proc. COPA*, PMLR 152, 2021.
15. J. Shin, A. Ramdas, A. Rinaldo, "E-detectors: a nonparametric framework for sequential change detection," *New England Journal of Statistics in Data Science*, 2023 (arXiv:2203.03532).
16. D. Prinster, X. Han, A. Liu, S. Saria, "WATCH: Adaptive Monitoring for AI Deployments via Weighted-Conformal Martingales," *ICML*, 2025.
17. L. Benfenati et al., "Foundation Models for Structural Health Monitoring," arXiv:2404.02944, 2024.
18. B. Peeters, G. De Roeck, "One-year monitoring of the Z24-Bridge: environmental effects versus damage events," *Earthquake Engineering & Structural Dynamics*, 30(2), 2001.
19. [FS-LSTM sensor-fault / damage isolation in SHM, NWPU — fill in the full citation]
20. [Stacked-GRU framework for isolating sensor failures and structural damage in noisy environments — fill in the full citation]

*(Check every reference against its original source before submitting.)*
