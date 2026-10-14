"""One command for the full live AIoT demo:

  MQTT broker -> 8 virtual accelerometer nodes + temperature node -> edge monitor (ShiftGuard)
  -> SQLite -> Streamlit dashboard + live digital twin (+ Node-RED email flow, if you import it)

  python run_demo.py                 # trains a model first if none exists, then opens the dashboard
  python run_demo.py --rate 8        # faster bridge time
  python run_demo.py --wokwi-id sg-ab12   # also bridge the Wokwi ESP32 temperature node
Stop with Ctrl+C. A component that crashes is restarted automatically (up to 5 times).
"""
import argparse
import os
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "iot"))
from common import port_open, wait_for_port  # noqa: E402

MAX_RESTARTS = 5


class Child:
    def __init__(self, name, cmd, env, critical=True, restart_args=()):
        self.name, self.cmd, self.env, self.critical = name, cmd, env, critical
        self.restart_args = list(restart_args)
        self.restarts = 0
        self.proc = None

    def start(self):
        print(f">> starting {self.name}", flush=True)
        self.proc = subprocess.Popen(self.cmd, cwd=ROOT, env=self.env)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--ws-port", type=int, default=9001, help="MQTT-over-WebSocket port used by the digital twin")
    ap.add_argument("--source", default="sim", choices=["sim", "z24"])
    ap.add_argument("--z24-dir", default=None)
    ap.add_argument("--z24-setup", default="0")
    ap.add_argument("--z24-channels", type=int, nargs="+", default=None)
    ap.add_argument("--model", default="ridge", choices=["mlp", "ridge"],
                    help="ridge: trains in under a minute and localises damage sharply (recommended for the live demo)")
    ap.add_argument("--rate", type=float, default=4.0)
    ap.add_argument("--dashboard-port", type=int, default=8501)
    ap.add_argument("--twin-port", type=int, default=8502)
    ap.add_argument("--wokwi-id", default=None, help="bridge the Wokwi ESP32 temperature node (see iot/wokwi_env_node)")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = ap.parse_args()

    model_file = os.path.join(ROOT, "models", f"shiftguard_{args.source}_{args.model}.pkl")
    if not os.path.exists(model_file):
        print(">> no trained monitor found - training one (takes ~1-3 minutes, only the first time)", flush=True)
        cmd = [PY, os.path.join(ROOT, "scripts", "train_monitor.py"), "--source", args.source, "--model", args.model,
               "--z24-setup", str(args.z24_setup)]
        if args.z24_dir:
            cmd += ["--z24-dir", args.z24_dir]
        if args.z24_channels:
            cmd += ["--z24-channels", *map(str, args.z24_channels)]
        subprocess.run(cmd, check=True, cwd=ROOT)

    env = dict(os.environ, SHM_BROKER=args.broker, SHM_PORT=str(args.port), SHM_WS_PORT=str(args.ws_port),
               PYTHONUNBUFFERED="1")
    children = []
    local = args.broker in ("localhost", "127.0.0.1")
    if local:
        if port_open("127.0.0.1", args.port):
            print(f">> an MQTT broker is already listening on port {args.port} - reusing it", flush=True)
        else:
            broker = Child("MQTT broker", [PY, "iot/broker.py", "--port", str(args.port), "--ws-port", str(args.ws_port)], env)
            broker.start(); children.append(broker)
            if not wait_for_port("127.0.0.1", args.port, 30):
                broker.stop()
                sys.exit(">> the MQTT broker did not start - see the error above")

    children.append(Child("edge monitor", [PY, "iot/edge_monitor.py", "--model", model_file,
                                           "--broker", args.broker, "--port", str(args.port)], env,
                          restart_args=["--resume"]))
    nodes = [PY, "iot/sensor_nodes.py", "--rate", str(args.rate), "--source", args.source,
             "--broker", args.broker, "--port", str(args.port), "--z24-setup", str(args.z24_setup)]
    if args.z24_dir:
        nodes += ["--z24-dir", args.z24_dir]
    if args.z24_channels:
        nodes += ["--z24-channels", *map(str, args.z24_channels)]
    children.append(Child("virtual sensor nodes", nodes, env))
    if args.wokwi_id:
        children.append(Child("Wokwi relay", [PY, "iot/wokwi_relay.py", "--wokwi-id", args.wokwi_id,
                                              "--broker", args.broker, "--port", str(args.port)], env, critical=False))
    if not args.no_dashboard:
        children.append(Child("digital twin page", [PY, "-m", "http.server", str(args.twin_port), "--bind", "127.0.0.1",
                                                    "--directory", os.path.join(ROOT, "dashboard", "static")],
                              dict(env, PYTHONUNBUFFERED="1"), critical=False))
        children.append(Child("dashboard", [PY, "-m", "streamlit", "run", "dashboard/app.py", "--server.headless", "true",
                                            "--browser.gatherUsageStats", "false",
                                            "--server.port", str(args.dashboard_port)],
                              dict(env, SHM_TWIN_URL=f"http://localhost:{args.twin_port}/twin.html")))
    for c in children:
        if c.proc is None:
            c.start()
            time.sleep(0.5)

    if not args.no_dashboard:
        print(f"\n>> Dashboard:     http://localhost:{args.dashboard_port}"
              f"\n>> Digital twin:  http://localhost:{args.twin_port}/twin.html?ws={args.ws_port}\n", flush=True)
        if not args.no_browser and wait_for_port("127.0.0.1", args.dashboard_port, 30):
            webbrowser.open(f"http://localhost:{args.dashboard_port}")
    try:
        while True:
            time.sleep(1)
            for c in children:
                code = c.proc.poll()
                if code is None:
                    continue
                if c.restarts >= MAX_RESTARTS:
                    if c.critical:
                        raise SystemExit(f">> {c.name} keeps crashing (exit code {code}); stopping the demo")
                    continue
                c.restarts += 1
                print(f">> {c.name} exited with code {code}; restarting ({c.restarts}/{MAX_RESTARTS})", flush=True)
                time.sleep(1)
                c.cmd = c.cmd + [a for a in c.restart_args if a not in c.cmd]
                c.start()
    except KeyboardInterrupt:
        pass
    finally:
        for c in children[::-1]:
            c.stop()
        for c in children:
            try:
                c.proc.wait(5)
            except subprocess.TimeoutExpired:
                c.proc.kill()
        print(">> stopped")


if __name__ == "__main__":
    main()
