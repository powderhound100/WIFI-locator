"""CSI frame model and parsers for the ESP32 esp-csi text format."""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np


@dataclass
class CsiFrame:
    node: str  # which sniffer/receiver captured it
    tx: str  # MAC of the transmitting device
    ts: float  # seconds
    rssi: int
    amp: np.ndarray  # per-subcarrier amplitude


def parse_esp32_line(line: str, node: str, ts: float) -> CsiFrame | None:
    """Parse one `CSI_DATA,...,"[i,q,i,q,...]"` line from esp-csi.

    Columns: 0 tag, 1 seq, 2 mac, 3 rssi, ... last is the I/Q byte array.
    Returns None for anything that is not a well-formed CSI line.
    """
    line = line.strip()
    if not line.startswith("CSI_DATA"):
        return None
    lb, rb = line.find("["), line.rfind("]")
    if lb < 0 or rb < lb:
        return None
    head = line[:lb].split(",")
    if len(head) < 4:
        return None
    try:
        raw = np.asarray(json.loads(line[lb : rb + 1]), dtype=np.float32)
        rssi = int(head[3])
    except (ValueError, TypeError):
        return None
    if raw.size < 2 or raw.size % 2:
        return None
    amp = np.hypot(raw[0::2], raw[1::2])
    return CsiFrame(node=node, tx=head[2].strip().lower(), ts=ts, rssi=rssi, amp=amp)
