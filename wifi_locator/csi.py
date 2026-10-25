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


def rssi_frame(node: str, tx: str, ts: float, dbm: float) -> CsiFrame:
    """Wrap an RSSI reading as a one-'subcarrier' frame (linear amplitude)."""
    return CsiFrame(node, tx.strip().lower(), ts, int(dbm), np.array([10 ** (dbm / 20)], dtype=np.float64))


def parse_rssi_line(line: str, node: str, ts: float) -> CsiFrame | None:
    """`RSSI,<transmitter mac>,<dbm>` as sent by wifi_locator.agent."""
    parts = line.strip().split(",")
    if len(parts) != 3 or parts[0] != "RSSI":
        return None
    try:
        return rssi_frame(node, parts[1], ts, float(parts[2]))
    except ValueError:
        return None


def parse_tshark_line(line: str, node: str, ts: float) -> CsiFrame | None:
    """`<wlan.ta>\t<radiotap.dbm_antsignal>` from tshark -T fields (monitor mode)."""
    ta, _, sig = line.rstrip("\n").partition("\t")
    if not ta or not sig:  # ACK/CTS frames carry no transmitter address
        return None
    try:
        dbm = float(sig.split(",")[0])  # several values when multi-antenna
    except ValueError:
        return None
    return rssi_frame(node, ta, ts, dbm)
