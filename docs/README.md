# ShiftGuard-SHM

**Damage, weather, or a broken sensor? Anytime-valid alarm attribution for software-simulated AIoT structural health monitoring.**

A software-only AIoT structural health monitoring system. A virtual sensor network streams
bridge vibration over MQTT to an edge monitor. For every alarm, the monitor says whether it
comes from **real structural damage**, **unusual weather** or a **faulty IoT sensor**. The false-alarm
guarantee holds over the whole monitoring period, not just one window at a time.

```
 Virtual IoT layer                     Edge analytics (ShiftGuard)                               Users
 ─────────────────                     ───────────────────────────                               ─────
 8 accelerometer nodes ─┐              ┌─ log band-power features per sensor
 (virtual bridge / Z24) │  MQTT        │
 temperature node ──────┼────────────► ├─ ① masked-sensor model: predict every sensor from the
 (or Wokwi ESP32+DHT22) │              │    others + temperature  → per-sensor residuals
 fault injector ────────┘              ├─ ② mask & impute the most suspicious sensor
 (drift, noise, dropout,               │    (also fills lost wireless packets)
  spikes, clipping, gain)              ├─ ③ temperature-localised conformal p-values
                                       ├─ ④ conformal e-detectors (CUSUM-type test martingales):
                                       │      STRUCTURE · SENSOR 1..N · ENVIRONMENT
                                       ├─ ⑤ attribution: DAMAGE / SENSOR FAULT / ENVIRONMENT
                                       └─ ⑥ severity: conformal prediction set {Moderate, Severe}
                                                │
                                                ├──► SQLite ──► Streamlit dashboard (live + injection buttons)
                                                └──► MQTT shm/<bridge>/alert ──► Node-RED ──► email
```

---

## Step 1: Install (5 minutes)

You need Python 3.10–3.13. No GPU and no hardware are needed.

```bash
cd shiftguard
python -m venv .venv
# Windows:  .venv\Scripts\activate          macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

## Step 2: Check that it works (30 seconds)

```bash
python tests/test_core.py
```
All six tests should print `ok`. They check that the conformal p-values are uniform, that the
e-values average to 1, that the false-alarm guarantee holds, and that the fault injector only
touches the target sensor.

## Step 3: Run the research experiment (paper tables and figures)

```bash
python scripts/run_experiment.py --model ridge --quick        # ~1 min smoke test
python scripts/run_experiment.py                              # full run: 1 seed, ~6 min
python scripts/run_experiment.py --seeds 0 1 2                # paper numbers, ~20 min
```

Each run does the following:
1. Simulates one healthy **training year**, one window per hour, with seasonal and daily temperature
   and varying traffic.
2. Simulates a **monitored year** with these events:
   - a cold snap colder than anything seen in training
   - 5 injected sensor faults: drift on S3, noise on S6, dropout on S1, spikes on S4 and clipping on S7
   - moderate damage at day 330, which becomes severe at day 348
3. Trains ShiftGuard and compares it with the old pipeline: an autoencoder-style score with a
   per-window conformal threshold.
4. Runs ablations, removing one component at a time.
5. Runs a **validity check**: a healthy-only year, to confirm the false-alarm guarantee.

The outputs are:
- `results/results.md`: tables for the paper
- `results/results.json`: the same numbers in raw form
- `results/figures/`:
  - `timeline.png`: the headline figure
  - `attribution_matrix.png`
  - `ablation.png`
  - `localisation.png`
- `models/shiftguard_sim_<model>.pkl`: the trained monitor, used by the live demo

You can define your own events in a JSON file and pass it with `--events my_events.json`. Use the format of
`DEFAULT_EVENTS` in `shiftguard/scenario.py`.

## Step 4: Live AIoT demo (for the review)

```bash
python run_demo.py
```
This one command starts these parts:
- an MQTT broker, written in pure Python, so no Mosquitto install is needed
- the edge monitor
- 8 virtual accelerometer nodes and 1 temperature node
- the dashboard at **http://localhost:8501**

If no trained model exists yet, it trains one first, which takes about 1–3 minutes.

**Demo script (about 3 minutes):**
1. Show the healthy bridge. The status shows ✅, the health score is near 100 and the evidence curves stay low.
2. In the sidebar, inject a fault: **Sensor 3 → drift → Inject**. After a few bridge-hours the status
   becomes 🔧 *Sensor fault — node S3*. There is **no damage alarm**. Point at the per-sensor bar chart, where only S3 is orange.
3. Click **Cold snap**. When the temperature drops below anything seen in training, the alarm is
   attributed to 🌡️ *Unprecedented environment*, not to damage.
4. Click **5 % packet loss**. Lost packets are imputed by the masked-sensor model, which you can see as `*` on the bar chart.
5. Click **Damage: moderate**. Within a few hours the status becomes 🚨 *Structural damage near sensors …*,
   with a conformal severity set. Then click **Damage: severe**.
6. Point at the two KPIs side by side: *ShiftGuard false-alarm hours* vs *per-window baseline false-alarm hours*.

You can also run each part in its own terminal and inject events from the command line:
```bash
python iot/broker.py
python iot/edge_monitor.py --model models/shiftguard_sim_ridge.pkl
python iot/sensor_nodes.py --rate 4
streamlit run dashboard/app.py
python iot/control.py fault --kind noise --sensor 6 --hours 48
python iot/control.py coldsnap --delta -12 --hours 96
python iot/control.py damage --level 1
python iot/control.py clear
```

These are the MQTT topics:

| Topic | Payload |
|---|---|
| `shm/bridge01/node/<i>/accel` | one acceleration window per node |
| `shm/bridge01/env/temperature` | temperature |
| `shm/bridge01/status` | ShiftGuard output for every window |
| `shm/bridge01/alert` | a message whenever the attribution changes |
| `shm/bridge01/control` | injection commands |
| `shm/bridge01/env/override` | an external temperature node |

## Step 5: Email alerts with Node-RED

1. Install Node-RED, then install `node-red-node-email` through *Manage palette*.
2. Go to *Menu → Import* and select `iot/nodered_flow.json`.
3. Open the **email** node. Set the recipient, and set the sender to a Gmail address with an
   [App Password](https://support.google.com/accounts/answer/185833). Then click Deploy.
4. With `run_demo.py` running, any **STRUCTURAL_DAMAGE** or **SENSOR_FAULT** alert is emailed.
   Weather and back-to-normal events go only to the debug log.

## Step 6 (optional): Wokwi ESP32 temperature node

The `iot/wokwi_env_node/` folder contains an ESP32 + DHT22 sketch and its `diagram.json`. Paste
both into a new ESP32 project on wokwi.com, then add the **PubSubClient** and **DHT sensor library** libraries.
Wokwi can only reach public brokers, so run the demo with:
```bash
python run_demo.py --broker broker.hivemq.com
```
Turn the DHT22 temperature knob in Wokwi to create a live cold snap.

**Note:** this sketch was not tested in Wokwi.

## Step 7: Use the real Z24 bridge data

1. Download `inputs.npy` (about 2 GB) and `labels.npy` from
   https://huggingface.co/datasets/thanglexuan/Z24-dataset-processed into `data/z24/`.
2. Check the files and their row order:
   ```bash
   python scripts/inspect_z24.py --z24-dir data/z24
   ```
3. Run the experiment and the live demo on Z24:
   ```bash
   python scripts/run_experiment.py --source z24 --z24-dir data/z24 --z24-setup 0
   python scripts/train_monitor.py  --source z24 --z24-dir data/z24
   python run_demo.py --source z24 --z24-dir data/z24
   ```

How Z24 is used:
- **Healthy data:** scenarios 1–2.
- **Moderate damage:** scenarios 3–7 and 9–11 (pier settlement, foundation tilt, spalling, landslide).
- **Severe damage:** scenarios 12–17 (concrete hinge, anchor heads, tendon rupture).
- **Scenario 8 is excluded.** It is the new reference after settlement, so it is neither clearly healthy nor damaged.
- **One sensor setup is used at a time,** because the cross-sensor model needs a fixed sensor layout.
- **Temperature effect:** the progressive-damage recordings have no temperature data. ShiftGuard adds the effect
  by replaying each recording √(stiffness ratio) faster, following the published Z24 frequency–temperature
  behaviour, which includes stiffening below 0 °C. Say this clearly in the paper.

---

## What is new (the research contribution)

| | Existing SHM work | ShiftGuard |
|---|---|---|
| Alarm logic | judges each window independently (a threshold, softmax output or per-window conformal) | accumulates evidence with **conformal test martingales / e-detectors** |
| Guarantee | per-window error rate, which still means hundreds of false alarms per year | **expected time to a false alarm ≥ c** over the whole monitoring period |
| Cause of an alarm | always reported as "anomaly / damage" | **three-way attribution:** damage, environment or a specific faulty sensor |
| Sensor faults and packet loss | assumed absent, or handled by a separate model | handled by the same **masked-sensor model**, which masks, imputes and localises |
| Temperature | removed by regression or PCA before detection | **temperature-conditioned model** plus **temperature-localised conformal calibration**, with an environment-novelty detector for conditions never seen |
| Validation | real sensors (no fault ground truth) | a **fault-injection protocol** with exact ground truth, made possible because sensing is software-defined |

The building blocks come from statistics and machine learning:
- conformal test martingales: Vovk et al., 2021
- e-detectors: Shin, Ramdas & Rinaldo, 2022
- weighted conformal monitoring: Prinster et al., ICML 2025

In our literature search, we did not find them applied to SHM, nor combined with damage, environment and
sensor-fault attribution. **Before submitting, re-check this on Scopus and IEEE Xplore.**

### Limitations to state in the paper
- The guarantee assumes exchangeable healthy data. Hourly windows are autocorrelated. Temperature-localised
  calibration and the validity-check year show that this works in practice, but the guarantee is approximate.
- The temperature effect on Z24 is simulated from published behaviour, not measured.
- The attribution rule assumes at most one faulty sensor at a time, because the masking step is single-sensor.

## Project structure

```
shiftguard/            core library
  config.py            all hyper-parameters
  sources.py           VirtualBridge (8-DOF bridge model) + Z24Source (replays Z24 recordings)
  environment.py       temperature profiles, stiffness-temperature law, temperature warp for Z24
  faults.py            IoT fault injector (gain, drift, noise, spikes, dropout, clipping)
  features.py          log band-power features, robust to one faulty sensor
  models.py            MaskedSensorNet (self-supervised neural network) + RidgeCrossSensor
  conformal.py         conformal p-values (global + temperature-localised), e-values, e-detector
  monitor.py           ShiftGuard: detectors, attribution, health score, severity sets
  baselines.py         per-window autoencoder-style baseline (the old pipeline)
  scenario.py          monitoring timelines with scheduled events
  plots.py             paper figures
scripts/               run_experiment.py, train_monitor.py, inspect_z24.py
iot/                   broker, sensor_nodes, edge_monitor, control, Node-RED flow, Wokwi sketch
dashboard/app.py       Streamlit live dashboard
run_demo.py            one-command live demo
tests/                 sanity tests
```

## Troubleshooting
- **`Address already in use` on port 1883:** another broker is running. Use it with `--broker localhost` and
  skip `iot/broker.py`, or pass `--port 1884` to everything.
- **The dashboard says "Waiting for the edge monitor":** start `run_demo.py`, or `iot/edge_monitor.py`.
- **Training is slow:** add `--model ridge`. It is about 10× faster with similar results.
- **Windows firewall prompt:** allow Python on private networks.
