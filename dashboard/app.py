"""ShiftGuard live dashboard (Streamlit).

  streamlit run dashboard/app.py
Reads the edge monitor's SQLite store and refreshes every 2 s. The sidebar buttons publish
control commands to the virtual sensor network, so faults / weather / damage can be injected
live during a demo.
"""
import json
import os
import sqlite3
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "iot"))
from common import DEFAULT_BROKER, DEFAULT_PORT, publish_command  # noqa: E402

DB = os.environ.get("SHM_DB", os.path.join(ROOT, "state", "live.db"))
C_ENV, C_FAULT, C_DMG, C_OK, INK2 = "#2a78d6", "#eb6834", "#d03b3b", "#0ca30c", "#52514e"
LABEL_STYLE = {
    "NORMAL": ("✅", "Structure healthy", C_OK),
    "ENVIRONMENT": ("🌡️", "Unprecedented environment", C_ENV),
    "SENSOR_FAULT": ("🔧", "Sensor fault", C_FAULT),
    "STRUCTURAL_DAMAGE": ("🚨", "Structural damage", C_DMG),
}

st.set_page_config(page_title="ShiftGuard SHM", page_icon="🌉", layout="wide")
st.title("ShiftGuard — AIoT Structural Health Monitoring")
st.caption("Masked-sensor model + conformal e-detectors: separates real damage from weather and broken sensors, "
           "with a guaranteed false-alarm rate.")

with st.sidebar:
    st.header("Live injection (virtual sensors)")
    broker = st.text_input("MQTT broker", DEFAULT_BROKER)
    port = st.number_input("Port", value=DEFAULT_PORT, step=1)

    def send(cmd):
        try:
            publish_command(cmd, broker, int(port)); st.toast(f"sent {cmd['cmd']}")
        except Exception as e:  # noqa: BLE001
            st.error(f"MQTT error: {e}")

    s = st.selectbox("Sensor", list(range(1, 9)), index=2)
    kind = st.selectbox("Fault type", ["drift", "noise", "dropout", "spikes", "clipping", "gain"])
    hrs = st.slider("Fault duration (bridge-hours)", 6, 168, 48)
    if st.button("Inject sensor fault", use_container_width=True):
        send(dict(cmd="fault", kind=kind, sensor=s, hours=hrs))
    if st.button("Cold snap (−12 °C, 4 days)", use_container_width=True):
        send(dict(cmd="coldsnap", delta=-12, hours=96))
    c1, c2 = st.columns(2)
    if c1.button("Damage: moderate", use_container_width=True):
        send(dict(cmd="damage", level=1))
    if c2.button("Damage: severe", use_container_width=True):
        send(dict(cmd="damage", level=2))
    if st.button("5 % packet loss", use_container_width=True):
        send(dict(cmd="packet_loss", p=0.05))
    if st.button("Clear all / repair", use_container_width=True):
        send(dict(cmd="clear"))
    window = st.slider("History shown (bridge-hours)", 48, 2000, 400)


@st.fragment(run_every=2)
def live():
    if not os.path.exists(DB):
        st.info("Waiting for the edge monitor … start it with `python run_demo.py`.")
        return
    con = sqlite3.connect(DB)
    try:
        w = pd.read_sql_query(f"SELECT * FROM windows ORDER BY seq DESC LIMIT {int(window)}", con).iloc[::-1]
        alerts = pd.read_sql_query("SELECT t_hours, label, message FROM alerts ORDER BY id DESC LIMIT 15", con)
        totals = pd.read_sql_query("SELECT COUNT(*) n, SUM(baseline_alarm) b, "
                                   "SUM(label!='NORMAL' AND truth='healthy') fa, SUM(baseline_alarm AND truth='healthy') bfa "
                                   "FROM windows", con).iloc[0]
    finally:
        con.close()
    if w.empty:
        st.info("Waiting for data …"); return
    last = w.iloc[-1]
    icon, text, col = LABEL_STYLE.get(last.label, ("", last.label, INK2))
    extra = ""
    if last.label == "SENSOR_FAULT":
        extra = f" — node S{int(last.fault_sensor)}"
    elif last.label == "STRUCTURAL_DAMAGE":
        extra = f" — near sensors {json.loads(last.location)}" + (f", severity {last.severity}" if last.severity else "")
    st.markdown(f"<div style='padding:14px 18px;border-radius:10px;border-left:8px solid {col};"
                f"background:rgba(127,127,127,.08);font-size:1.4rem'><b>{icon} {text}{extra}</b>"
                f"<span style='float:right;font-size:1rem;color:{INK2}'>bridge hour {last.t_hours:.0f} · "
                f"truth: {last.truth}</span></div>", unsafe_allow_html=True)

    k = st.columns(5)
    k[0].metric("Health score", f"{last.health:.0f}/100")
    k[1].metric("Temperature", f"{last.temp:.1f} °C")
    k[2].metric("Windows analysed", int(totals.n))
    k[3].metric("ShiftGuard false-alarm hours", int(totals.fa or 0))
    k[4].metric("Per-window baseline false-alarm hours", int(totals.bfa or 0))

    left, right = st.columns([2, 1])
    with left:
        fig = go.Figure()
        for y, name, c in [(w.ev_env, "Environment", C_ENV), (w.ev_sensor_max, "Sensors (max)", C_FAULT),
                           (w.ev_struct, "Structure", C_DMG)]:
            fig.add_trace(go.Scatter(x=w.t_hours, y=y.clip(lower=1e-2), name=name, line=dict(color=c, width=2)))
        fig.add_hline(y=1e4, line_dash="dash", annotation_text="alarm threshold", line_color=INK2)
        fig.update_yaxes(type="log", title="accumulated evidence")
        fig.update_xaxes(title="bridge hour")
        fig.update_layout(height=330, margin=dict(l=10, r=10, t=30, b=10), title="Conformal e-detectors",
                          legend=dict(orientation="h", y=1.12), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        ft = go.Figure(go.Scatter(x=w.t_hours, y=w.temp, line=dict(color=INK2, width=1.5), name="°C"))
        ft.update_layout(height=180, margin=dict(l=10, r=10, t=30, b=10), title="Temperature (°C)")
        st.plotly_chart(ft, use_container_width=True)
    with right:
        sc = json.loads(last.sensor_scores)
        imp = set(json.loads(last.imputed or "[]"))
        cols = [C_FAULT if (last.label == "SENSOR_FAULT" and i + 1 == last.fault_sensor) else
                C_DMG if (last.label == "STRUCTURAL_DAMAGE" and i + 1 in json.loads(last.location)) else "#9b9a95"
                for i in range(len(sc))]
        fb = go.Figure(go.Bar(x=[f"S{i+1}{'*' if i+1 in imp else ''}" for i in range(len(sc))], y=sc, marker_color=cols))
        fb.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10),
                         title="Per-sensor disagreement (latest window)", yaxis_title="residual")
        st.plotly_chart(fb, use_container_width=True)
        if imp:
            st.caption(f"* packet lost and imputed by the masked-sensor model: {sorted(imp)}")
        st.markdown("**Attribution timeline**")
        order = {"NORMAL": 0, "ENVIRONMENT": 1, "SENSOR_FAULT": 2, "STRUCTURAL_DAMAGE": 3}
        fa = go.Figure(go.Scatter(x=w.t_hours, y=w.label.map(order), mode="markers",
                                  marker=dict(size=5, color=[LABEL_STYLE[l][2] for l in w.label])))
        fa.update_yaxes(tickvals=[0, 1, 2, 3], ticktext=["Normal", "Environment", "Sensor fault", "Damage"], range=[-0.5, 3.5])
        fa.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fa, use_container_width=True)

    st.subheader("Alert log (also sent to Node-RED → email)")
    st.dataframe(alerts, use_container_width=True, hide_index=True)


live()
