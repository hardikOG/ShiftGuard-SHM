"""Inject events into the running virtual sensor network (live demo).

  python iot/control.py fault --kind drift --sensor 3 --hours 72
  python iot/control.py fault --kind noise --sensor 6
  python iot/control.py fault --kind dropout --sensor 1 --hours 24
  python iot/control.py coldsnap --delta -12 --hours 96
  python iot/control.py damage --level 1          # 1 = moderate, 2 = severe, 0 = repair
  python iot/control.py packet_loss --p 0.05
  python iot/control.py speed --rate 8
  python iot/control.py clear
"""
import argparse

from common import DEFAULT_BROKER, DEFAULT_PORT, publish_command
from shiftguard.faults import FAULT_KINDS

ap = argparse.ArgumentParser()
ap.add_argument("--broker", default=DEFAULT_BROKER)
ap.add_argument("--port", type=int, default=DEFAULT_PORT)
sub = ap.add_subparsers(dest="cmd", required=True)
f = sub.add_parser("fault"); f.add_argument("--kind", choices=FAULT_KINDS, default="drift")
f.add_argument("--sensor", type=int, default=3); f.add_argument("--hours", type=float, default=48)
f.add_argument("--severity", type=float, default=1.0)
c = sub.add_parser("coldsnap"); c.add_argument("--delta", type=float, default=-12); c.add_argument("--hours", type=float, default=96)
d = sub.add_parser("damage"); d.add_argument("--level", type=int, choices=[0, 1, 2], default=1)
p = sub.add_parser("packet_loss"); p.add_argument("--p", type=float, default=0.05)
s = sub.add_parser("speed"); s.add_argument("--rate", type=float, default=4)
sub.add_parser("clear")
args = ap.parse_args()
cmd = {k: v for k, v in vars(args).items() if k not in ("broker", "port")}
publish_command(cmd, args.broker, args.port)
print("sent", cmd)
