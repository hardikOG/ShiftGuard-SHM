"""One command for the full live AIoT demo:

  MQTT broker -> 8 virtual accelerometer nodes + temperature node -> edge monitor (ShiftGuard)
  -> SQLite -> Streamlit dashboard (+ Node-RED email flow, if you import it)

  python run_demo.py                 # trains a model first if none exists, then opens the dashboard
  python run_demo.py --rate 8        # faster bridge time
  python run_demo.py --broker broker.hivemq.com   # use a public broker (needed for Wokwi)
Stop with Ctrl+C.
"""
import argparse
import os
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--source", default="sim", choices=["sim", "z24"])
    ap.add_argument("--z24-dir", default=None)
    ap.add_argument("--model", default="ridge", choices=["mlp", "ridge"],
                    help="ridge: trains in ~1 min and localises damage sharply (recommended for the live demo)")
    ap.add_argument("--rate", type=float, default=4.0)
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = ap.parse_args()

    model_file = os.path.join(ROOT, "models", f"shiftguard_{args.source}_{args.model}.pkl")
    if not os.path.exists(model_file):
        print(">> no trained monitor found - training one (takes ~1-3 minutes, only the first time)")
        cmd = [PY, os.path.join(ROOT, "scripts", "train_monitor.py"), "--source", args.source, "--model", args.model]
        if args.z24_dir:
            cmd += ["--z24-dir", args.z24_dir]
        subprocess.run(cmd, check=True, cwd=ROOT)

    env = dict(os.environ, SHM_BROKER=args.broker, SHM_PORT=str(args.port), PYTHONUNBUFFERED="1")
    procs = []

    def start(name, cmd):
        print(f">> starting {name}")
        procs.append(subprocess.Popen(cmd, cwd=ROOT, env=env))
        time.sleep(1.5)

    if args.broker in ("localhost", "127.0.0.1"):
        start("MQTT broker", [PY, "iot/broker.py", "--port", str(args.port)])
    start("edge monitor", [PY, "iot/edge_monitor.py", "--model", model_file, "--broker", args.broker, "--port", str(args.port)])
    nodes = [PY, "iot/sensor_nodes.py", "--rate", str(args.rate), "--source", args.source,
             "--broker", args.broker, "--port", str(args.port)]
    if args.z24_dir:
        nodes += ["--z24-dir", args.z24_dir]
    start("virtual sensor nodes", nodes)
    if not args.no_dashboard:
        start("dashboard", [PY, "-m", "streamlit", "run", "dashboard/app.py", "--server.headless", "true",
                            "--browser.gatherUsageStats", "false", "--server.port", "8501"])
        print("\n>> Dashboard: http://localhost:8501   (inject faults / damage from its sidebar)\n")
        if not args.no_browser:
            time.sleep(2)
            webbrowser.open("http://localhost:8501")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs[::-1]:
            p.terminate()
        for p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        print(">> stopped")


if __name__ == "__main__":
    main()
