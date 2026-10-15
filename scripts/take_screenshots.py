"""Capture the README screenshots from the running live demo.

Start the demo first (python run_demo.py), then:
  python scripts/take_screenshots.py

Drives the demo through four situations (healthy, broken sensor, unusual weather, damage), waits until
the edge monitor has actually reached each verdict, and screenshots the live bridge page and the
dashboard with headless Microsoft Edge (DevTools protocol, 2x pixel density) into docs/screenshots/.
"""
import asyncio
import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "iot"))
from common import DEFAULT_BROKER, DEFAULT_PORT, dumps, make_client, publish_command, topic  # noqa: E402

OUT = os.path.join(ROOT, "docs", "screenshots")
DB = os.path.join(ROOT, "state", "live.db")
TWIN = "http://localhost:8502/twin.html?ws=9001"
DASH = "http://localhost:8501"
PORT = 9333
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)
# Streamlit draws its tabs after the page loads, so keep trying until the "Details" tab exists
OPEN_DETAILS_TAB = """new Promise(done => { const timer = setInterval(() => {
  const tab = [...document.querySelectorAll('[role=tab]')].find(t => t.innerText.includes('Details'));
  if (tab) { tab.click(); clearInterval(timer); done(true); } }, 300); })"""


def latest():
    con = sqlite3.connect(DB)
    try:
        return con.execute("SELECT label, fault_sensor FROM windows ORDER BY seq DESC LIMIT 1").fetchone()
    finally:
        con.close()


def wait_for(label, sensor=None, timeout=120, settle=8):
    """Wait until the edge monitor reports `label` and keeps reporting it for `settle` seconds."""
    t_end, since = time.time() + timeout, None
    while time.time() < t_end:
        got = latest()
        ok = got and got[0] == label and (sensor is None or got[1] == sensor)
        since = (since or time.time()) if ok else None
        if since and time.time() - since >= settle:
            return
        time.sleep(1)
    raise TimeoutError(f"edge monitor never reported {label} (last: {latest()})")


class ColdSensor:
    """Acts like the Wokwi DHT22 / the twin's temperature slider: keeps overriding the temperature."""

    def __init__(self, temp):
        self.temp, self.client = temp, make_client(f"shm-shot-{os.getpid()}")
        self.client.connect(DEFAULT_BROKER, DEFAULT_PORT, 30)
        self.client.loop_start()
        self.running = True
        import threading
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            self.client.publish(topic("env", "override"), dumps({"temp": self.temp, "source": "screenshot"}))
            time.sleep(1)

    def stop(self):
        self.running = False
        self.client.loop_stop(); self.client.disconnect()


async def shot(ws, url, out, width, height, wait, js=None):
    n = [0]

    async def call(method, **params):
        n[0] += 1
        await ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == n[0]:
                return msg.get("result", {})

    await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2, mobile=False)
    await call("Page.navigate", url=url)
    await asyncio.sleep(wait)
    if js:
        await call("Runtime.evaluate", expression=js, awaitPromise=True)
        await asyncio.sleep(5)
    data = (await call("Page.captureScreenshot", format="png"))["data"]
    with open(out, "wb") as f:
        f.write(base64.b64decode(data))
    print("  saved", os.path.relpath(out, ROOT))


async def run():
    targets = None
    for _ in range(50):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            break
        except OSError:
            time.sleep(0.2)
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
    async with websockets.connect(ws_url, max_size=None) as ws:
        twin = lambda name: shot(ws, TWIN, os.path.join(OUT, name), 1100, 900, 7)
        if os.environ.get("ONLY_DASHBOARD"):
            await shot(ws, DASH, os.path.join(OUT, "6_dashboard_details.png"), 1300, 1000, 8, OPEN_DETAILS_TAB)
            return
        print("1/4 healthy bridge")
        publish_command({"cmd": "clear"}); wait_for("NORMAL")
        await twin("1_healthy.png")
        print("2/4 broken sensor (noise on S3)")
        publish_command({"cmd": "fault", "kind": "noise", "sensor": 3, "hours": 400}); wait_for("SENSOR_FAULT", 3)
        await twin("2_sensor_fault.png")
        print("3/4 unusual weather (cold snap)")
        publish_command({"cmd": "clear"}); wait_for("NORMAL")
        cold = ColdSensor(-25.0)
        try:
            wait_for("ENVIRONMENT", settle=4)
            await twin("3_weather.png")
        finally:
            cold.stop()
        time.sleep(31)                      # the override expires after 30 s without updates
        print("4/4 structural damage")
        publish_command({"cmd": "clear"}); wait_for("NORMAL")
        publish_command({"cmd": "damage", "level": 2}); wait_for("STRUCTURAL_DAMAGE")
        await twin("4_damage.png")
        await shot(ws, DASH, os.path.join(OUT, "5_dashboard.png"), 1300, 1000, 8)
        await shot(ws, DASH, os.path.join(OUT, "6_dashboard_details.png"), 1300, 1000, 8, OPEN_DETAILS_TAB)
        publish_command({"cmd": "clear"})


def main():
    if EDGE is None:
        sys.exit("Microsoft Edge not found")
    os.makedirs(OUT, exist_ok=True)
    proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"])
    try:
        asyncio.run(run())
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
