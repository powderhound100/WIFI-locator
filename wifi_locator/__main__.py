"""python -m wifi_locator --simulate | --config config.json"""
from __future__ import annotations

import argparse
import json

from aiohttp import web

from .detector import MotionEngine
from .server import make_app
from .sources import Simulator, run_serial, run_simulator, run_udp


def main() -> None:
    p = argparse.ArgumentParser(description="WiFi CSI motion dashboard")
    p.add_argument("--config", help="JSON config (see config.example.json)")
    p.add_argument("--simulate", action="store_true", help="synthetic data, no hardware")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()

    cfg = json.load(open(a.config)) if a.config else {}
    zones = {n["name"]: n.get("zone", n["name"]) for n in cfg.get("nodes", [])}
    engine = MotionEngine(zones=zones, calib_seconds=cfg.get("calibration_seconds", 30))
    sink = engine.feed

    sources = []
    if a.simulate or not cfg:
        zones.update({"hall": "Hallway", "living": "Living room", "bed": "Bedroom"})
        sim = Simulator({n: ["aa:00:00:00:00:01", "aa:00:00:00:00:02"] for n in zones})
        sources.append(run_simulator(sink, sim))
    else:
        ips = {n["ip"]: n["name"] for n in cfg["nodes"] if "ip" in n}
        if ips:
            sources.append(run_udp(sink, cfg.get("udp_port", 5005), ips))
        for n in cfg["nodes"]:
            if "serial" in n:
                sources.append(run_serial(sink, n["serial"], n["name"]))

    web.run_app(make_app(engine, sources), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
