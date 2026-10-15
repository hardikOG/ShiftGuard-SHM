"""ShiftGuard live dashboard (Streamlit).

  streamlit run dashboard/app.py
Tab 1 embeds the live digital twin (where faults, weather and damage are injected).
Tab 2 reads the edge monitor's SQLite store and refreshes every 2 s.
"""
import os
import sqlite3

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = os.path.join(os.path.dirname(__file__), "..")
DB = os.environ.get("SHM_DB", os.path.join(ROOT, "state", "live.db"))
TWIN_URL = os.environ.get("SHM_TWIN_URL", "http://localhost:8502/twin.html")
WS_PORT = os.environ.get("SHM_WS_PORT", "9001")
HISTORY_HOURS = 400
SETTLE_HOURS = 24
VERDICT = {
    "NORMAL": ("✅", "Bridge is healthy", "#18a058"),
    "ENVIRONMENT": ("🌡️", "Unusual weather — not damage", "#2a78d6"),
    "SENSOR_FAULT": ("🔧", "A sensor is broken — not damage", "#eb6834"),
    "STRUCTURAL_DAMAGE": ("🚨", "Structural damage detected", "#d03b3b"),
}

st.set_page_config(page_title="ShiftGuard SHM", page_icon="🌉", layout="wide", initial_sidebar_state="collapsed")
st.title("🌉 ShiftGuard")
st.caption("Tells apart real bridge damage, unusual weather and broken sensors — with very few false alarms.")


@st.fragment(run_every=2)
def details():
    if not os.path.exists(DB):
        st.info("Waiting for data … start everything with `python run_demo.py`.")
        return
    con = sqlite3.connect(DB)
    try:
        w = pd.read_sql_query(f"SELECT * FROM windows ORDER BY seq DESC LIMIT {HISTORY_HOURS}", con).iloc[::-1]
        alerts = pd.read_sql_query("SELECT t_hours AS 'bridge hour', message FROM alerts ORDER BY id DESC LIMIT 10", con)
        hist = pd.read_sql_query("SELECT t_hours, label, truth, baseline_alarm, proc_ms FROM windows ORDER BY seq", con)
    except (sqlite3.Error, pd.errors.DatabaseError):
        st.info("Waiting for data …"); return
    finally:
        con.close()
    if w.empty:
        st.info("Waiting for data …"); return
    # False alarms are counted on settled healthy hours only: right after a repair the evidence needs a
    # few hours to decay, which is recovery, not a false alarm (same rule as the live bridge page).
    event_t = hist.t_hours.where(hist.truth.fillna("healthy") != "healthy").ffill()
    settled = (hist.truth == "healthy") & ~((hist.t_hours - event_t) <= SETTLE_HOURS)
    totals = pd.Series(dict(fa=int((settled & (hist.label != "NORMAL")).sum()),
                            bfa=int((settled & (hist.baseline_alarm == 1)).sum()), ms=hist.proc_ms.mean()))
    last = w.iloc[-1]
    icon, text, col = VERDICT.get(last.label, ("", last.label, "#6b7380"))
    st.markdown(f"<div style='padding:16px 20px;border-radius:12px;border-left:10px solid {col};"
                f"background:rgba(127,127,127,.08);font-size:1.5rem'><b>{icon} {text}</b></div>",
                unsafe_allow_html=True)
    st.write("")

    k = st.columns(4)
    k[0].metric("Health", f"{last.health:.0f} / 100")
    k[1].metric("Temperature", f"{last.temp:.1f} °C")
    k[2].metric("False alarms (ours vs old)", f"{int(totals.fa or 0)} vs {int(totals.bfa or 0)}")
    k[3].metric("Analysis time", f"{(totals.ms or 0):.1f} ms")

    fig = go.Figure()
    for y, name, c in [(w.ev_struct, "Damage", "#d03b3b"), (w.ev_sensor_max, "Broken sensor", "#eb6834"),
                       (w.ev_env, "Unusual weather", "#2a78d6")]:
        fig.add_trace(go.Scatter(x=w.t_hours, y=y.clip(lower=1e-2), name=name, line=dict(color=c, width=2)))
    fig.add_hline(y=1e4, line_dash="dash", annotation_text="alarm", line_color="#6b7380")
    fig.update_yaxes(type="log", title="evidence", showticklabels=False)
    fig.update_xaxes(title="bridge hour")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=60), title="How sure is ShiftGuard? (alarm when a line crosses the dashed line)",
                      legend=dict(orientation="h", y=-0.25), hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    st.subheader("Alerts")
    if alerts.empty:
        st.caption("No alerts yet.")
    else:
        st.dataframe(alerts, width="stretch", hide_index=True)


tab_twin, tab_details = st.tabs(["🌉 Live bridge", "📈 Details"])
with tab_twin:
    if hasattr(st, "iframe"):
        st.iframe(f"{TWIN_URL}?ws={WS_PORT}", height=980)
    else:                                                    # Streamlit < 1.52
        components.iframe(f"{TWIN_URL}?ws={WS_PORT}", height=980, scrolling=True)
    st.caption(f"Open full screen: {TWIN_URL}?ws={WS_PORT}")
with tab_details:
    details()
