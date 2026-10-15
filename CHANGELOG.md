# Changelog

## 1.2.0
- **Simpler UI.**
  - Live bridge page: one verdict, the bridge, and three buttons; extras are under *More controls*.
  - Dashboard: opens on the live bridge; one chart and the alerts are under *Details*.
- **Real Z24 results** (both models, 3 seeds) in `results_z24*/` and the paper's Table III. They use the 8 channels shared by all Z24 sensor setups (`--z24-setup all --z24-channels ...`).
- **Fixes:**
  - Hours under a temperature override (Wokwi DHT22 / slider) are now labelled as an environment event. Before, they counted as false alarms.
  - The dashboard counts false alarms only on settled healthy hours, the same rule as the live bridge page.
- **Paper:** IEEE LaTeX source in `paper/latex/` with review fixes (Kullaa 2011 reference, Z24 citations, measured c = 10^5 trade-off, Figure 3 label order) and a code-availability link.
- **Docs:**
  - a short README with live screenshots; `scripts/take_screenshots.py` regenerates them
  - the full guide is in `docs/GUIDE.md`
  - the Review-2 deck is in `review_deck/`

## 1.1.0

### Method fix (changes the paper numbers)
- **The per-sensor detectors now use mask-and-impute scores**, as Section IV of the paper describes.
  - Before: the per-sensor detectors used raw residuals. A faulty sensor inflated the residuals of the
    neighbours predicted from it, their detectors crossed the threshold too, and when the fault ended the
    alarm passed to a neighbour (e.g. drift on S3 was reported as "sensor fault S5" for a few hours).
  - Now: after imputing the worst sensor j*, every other sensor is re-scored. Detection and attribution
    are unchanged, and false-alarm hours drop (ridge, 3 seeds: 34.7 → 23.3 h; episodes 8 → 6.7).
  - `results/` and `results_ridge/` have been regenerated.

### Live digital twin (new)
- `dashboard/static/twin.html`: an interactive browser model of the bridge, connected to the broker over
  MQTT-over-WebSocket.
  - The deck is animated from the live accelerometer windows.
  - Click a node to break or repair it. Cold snap, damage, packet loss, speed and pause controls.
  - A virtual DHT22 slider, an oscilloscope, all ten e-detectors, and the edge latency.
- Served by `run_demo.py` on port 8502, and embedded in the Streamlit dashboard as a tab.

### Reliability
- **MQTT clients** reconnect with back-off and re-subscribe on every connect, so they survive a broker
  restart.
- **`run_demo.py`**:
  - waits for the broker port instead of a fixed sleep
  - reuses an existing broker
  - restarts crashed components up to 5 times; the edge restarts with `--resume`
- **Edge monitor**:
  - processes windows in strict sequence order. Before, a late window could be fed to the sequential
    detectors out of order.
  - computes features from the received channels only and imputes missing sensors iteratively. Before,
    zero-filled channels biased the excitation normalisation.
  - detects a restarted sensor network and appends to the history instead of overwriting it
  - isolates per-window errors so one bad window does not stop monitoring
  - measures latency per window
  - alerts on severity escalation
- **Ground truth:** the edge could process a window before its ground-truth message arrived and then never
  record ground truth at all. The dashboard's false-alarm KPIs stayed at 0. Fixed.
- **Sensor network**:
  - validates every control command. Before, e.g., `speed --rate 0` crashed it with a division by zero.
  - holds a lock around state shared with the MQTT thread
  - publishes a retained `sim/state` topic
  - adds `pause`, `resume` and `repair_sensor` commands
- **Broker**: refuses to start on a busy port (on Windows, `SO_REUSEADDR` would let two brokers split the
  clients silently) and adds a WebSocket listener.
- **Monitor**: always picklable. The global-calibration ablation used to store lambdas.
- **Wokwi**:
  - `iot/wokwi_relay.py` bridges only the ESP32 temperature topic from the public broker, instead of
    moving all sensor data onto it.
  - The sketch has a unique `WOKWI_ID` and status LEDs.
- **Node-RED**: ignores the retained alert, so a restart does not re-send an email.
- **Dashboard**: removed deprecated Streamlit arguments and shows the edge latency.

### Tests
- `tests/test_system.py` (11 new tests) covers:
  - fault attribution, and no evidence left on the faulty sensor's neighbours
  - damage detection and localisation
  - unseen cold attributed to the environment
  - a silent healthy stream
  - online and offline runs agree
  - pickling
  - lost-packet imputation
  - command validation
  - a multi-process MQTT test with 20 % packet loss and a sensor-network restart
