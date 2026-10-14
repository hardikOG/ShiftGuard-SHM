"""Local MQTT broker in pure Python (no Mosquitto install needed).

  python iot/broker.py            # listens on 0.0.0.0:1883
If you already run Mosquitto / HiveMQ, skip this and point the other scripts at it with --broker.
"""
import argparse
import asyncio
import logging

from amqtt.broker import Broker


async def main(port):
    cfg = {
        "listeners": {"default": {"type": "tcp", "bind": f"0.0.0.0:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }
    broker = Broker(cfg)
    await broker.start()
    print(f"[broker] MQTT broker running on port {port} (Ctrl+C to stop)", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(main(args.port))
    except KeyboardInterrupt:
        pass
