"""Run on a PC to report its own signal strength to the access point over UDP.

    python -m wifi_locator.agent --server 192.168.1.10 [--port 5005] [--iface wlan0]

Linux uses `iw`; Windows uses `netsh` (1% steps, so coarser). The dashboard host
maps this PC's IP to a zone in config.json like any other node.
"""
from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time


def read_linux(iface: str) -> tuple[str, float] | None:
    out = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True).stdout
    b, s = re.search(r"Connected to ([0-9a-f:]{17})", out, re.I), re.search(r"signal:\s*(-?\d+)", out)
    return (b.group(1), float(s.group(1))) if b and s else None


def read_windows(_iface: str) -> tuple[str, float] | None:
    out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True).stdout
    b = re.search(r"BSSID\s*:\s*([0-9a-f:]{17})", out, re.I)
    s = re.search(r"Signal\s*:\s*(\d+)%", out)
    return (b.group(1), int(s.group(1)) / 2 - 100) if b and s else None  # usual %->dBm approximation


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True)
    p.add_argument("--port", type=int, default=5005)
    p.add_argument("--iface", default="wlan0")
    p.add_argument("--hz", type=float, default=5.0)
    a = p.parse_args()
    read = read_windows if sys.platform.startswith("win") else read_linux
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        r = read(a.iface)
        if r:
            sock.sendto(f"RSSI,{r[0]},{r[1]}\n".encode(), (a.server, a.port))
        time.sleep(1 / a.hz)


if __name__ == "__main__":
    main()
