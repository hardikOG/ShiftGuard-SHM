"""Screenshot a live page with headless Edge over the DevTools protocol, after its data has arrived.

  python cdp_shot.py <url> <out.png> [wait_seconds]
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

EDGE = next(p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p))
PORT = 9333


async def shoot(url, out, wait):
    ws_url = None
    for _ in range(50):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
            break
        except Exception:
            time.sleep(0.2)
    async with websockets.connect(ws_url, max_size=None) as ws:
        n = 0

        async def call(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == n:
                    return msg.get("result", {})

        await call("Emulation.setDeviceMetricsOverride", width=1100, height=640, deviceScaleFactor=2, mobile=False)
        await call("Page.navigate", url=url)
        await asyncio.sleep(wait)
        shot = await call("Page.captureScreenshot", format="png")
        open(out, "wb").write(base64.b64decode(shot["data"]))


def main():
    url, out = sys.argv[1], sys.argv[2]
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 8
    profile = tempfile.mkdtemp()
    proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "about:blank"])
    try:
        asyncio.run(shoot(url, out, wait))
    finally:
        proc.terminate()
    print("saved", out)


if __name__ == "__main__":
    main()
