"""Local MQTT broker in pure Python (no Mosquitto install needed).

  python iot/broker.py                     # MQTT on 0.0.0.0:1883, MQTT-over-WebSocket on :9001
If you already run Mosquitto / HiveMQ, skip this and point the other scripts at it with --broker.
The WebSocket listener is what the browser digital twin connects to.
"""
import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DEFAULT_PORT, DEFAULT_WS_PORT, port_open  # noqa: E402

from amqtt.broker import Broker  # noqa: E402


async def main(port, ws_port):
    listeners = {"default": {"type": "tcp", "bind": f"0.0.0.0:{port}"}}
    if ws_port:
        listeners["ws"] = {"type": "ws", "bind": f"0.0.0.0:{ws_port}"}
    cfg = {
        "listeners": listeners,
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }
    broker = Broker(cfg)
    await broker.start()
    print(f"[broker] MQTT broker running on port {port}" + (f", WebSocket on {ws_port}" if ws_port else "")
          + " (Ctrl+C to stop)", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--ws-port", type=int, default=DEFAULT_WS_PORT, help="0 disables the WebSocket listener")
    args = ap.parse_args()
    # amqtt binds with SO_REUSEADDR, which on Windows lets a SECOND broker bind the same port and
    # silently split the clients between two brokers. Refuse instead.
    for p in (args.port, args.ws_port):
        if p and port_open("127.0.0.1", p):
            sys.exit(f"[broker] port {p} is already in use - another broker is probably running. "
                     f"Reuse it (skip this script) or pick another port.")
    logging.basicConfig(level=logging.WARNING)
    # run_demo.py checks readiness by opening and closing a TCP connection; amqtt logs that as an error
    probe_noise = ("No data to decode MQTT packet", "No data from")
    logging.getLogger("amqtt.broker").addFilter(lambda r: not any(s in r.getMessage() for s in probe_noise))
    try:
        asyncio.run(main(args.port, args.ws_port))
    except KeyboardInterrupt:
        pass
