"""Relay the Wokwi ESP32 temperature node from a public broker into the local pipeline.

Wokwi simulates the ESP32 in the browser and can only reach public brokers. Instead of moving the
whole sensor network to a public broker (every window is ~160 kB of acceleration data, readable by
anyone), only the ESP32's temperature topic is bridged:

  public broker  shm/<wokwi-id>/env/override  ->  local broker  shm/<bridge>/env/override

  python iot/wokwi_relay.py --wokwi-id sg-ab12cd     # the same id as WOKWI_ID in sketch.ino
"""
import argparse
import json

from common import DEFAULT_BROKER, DEFAULT_PORT, connect, dumps, make_client, topic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wokwi-id", required=True, help="unique id, must match WOKWI_ID in sketch.ino")
    ap.add_argument("--public-broker", default="broker.hivemq.com")
    ap.add_argument("--public-port", type=int, default=1883)
    ap.add_argument("--broker", default=DEFAULT_BROKER)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    remote_topic = f"shm/{args.wokwi_id}/env/override"
    local = make_client(f"shm-wokwi-local-{args.wokwi_id}")
    connect(local, args.broker, args.port, name="wokwi-relay/local")
    local.loop_start()

    def on_message(c, u, msg):
        try:
            temp = float(json.loads(msg.payload)["temp"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return
        if -50 <= temp <= 60:                      # ignore garbage published by strangers
            local.publish(topic("env", "override"), dumps({"temp": temp, "source": "wokwi"}), qos=0)
            print(f"[wokwi-relay] ESP32 temperature {temp:.1f} C", flush=True)

    remote = make_client(f"shm-wokwi-remote-{args.wokwi_id}")
    remote.on_message = on_message
    connect(remote, args.public_broker, args.public_port, [(remote_topic, 0)], name="wokwi-relay/public")
    print(f"[wokwi-relay] {args.public_broker}:{remote_topic} -> {args.broker}:{topic('env', 'override')}", flush=True)
    try:
        remote.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        pass
    finally:
        local.loop_stop()


if __name__ == "__main__":
    main()
