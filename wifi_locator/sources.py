"""Frame sources: simulator, UDP (ESP32 nodes), and serial."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import numpy as np

from .csi import CsiFrame, parse_esp32_line

Sink = Callable[[CsiFrame], None]


class Simulator:
    """Synthetic multipath channel. Movement adds a time-varying component
    to the static channel on links in the zone where someone is walking."""

    def __init__(self, layout: dict[str, list[str]], n_sub: int = 52, seed: int = 0):
        # layout: node -> list of transmitting MACs it hears
        rng = np.random.default_rng(seed)
        self.rng = rng
        self.layout = layout
        self.links = {}
        for node, txs in layout.items():
            for tx in txs:
                h0 = rng.normal(size=n_sub) + 1j * rng.normal(size=n_sub) + 3
                phase = rng.uniform(0, 2 * np.pi, size=(n_sub, 4))
                freq = rng.uniform(0.5, 3.0, size=4)
                self.links[(node, tx)] = (h0, phase, freq)
        self.active: set[str] = set()  # nodes whose area has movement

    def frame(self, node: str, tx: str, t: float) -> CsiFrame:
        h0, phase, freq = self.links[(node, tx)]
        h = h0.copy()
        if node in self.active:
            dyn = np.exp(1j * (2 * np.pi * freq * t + phase)).sum(axis=1)
            h += 0.25 * np.abs(h0).mean() * dyn
        h += self.rng.normal(scale=0.02, size=h.shape) * np.abs(h0).mean()
        amp = np.abs(h) * self.rng.uniform(0.9, 1.1)  # AGC jitter
        return CsiFrame(node, tx, t, int(-50 + self.rng.integers(-2, 3)), amp.astype(np.float32))

    def tick(self, t: float):
        for node, tx in self.links:
            yield self.frame(node, tx, t)


async def run_simulator(sink: Sink, sim: Simulator, rate: float = 40.0) -> None:
    """Real-time simulation; a random area gets 'movement' every ~20s."""
    nodes = list(sim.layout)
    t0 = time.monotonic()
    next_toggle = 0.0
    while True:
        now = time.monotonic()
        t = now - t0
        if t >= next_toggle:
            sim.active = {sim.rng.choice(nodes)} if not sim.active and t > 35 else set()
            next_toggle = t + (10 if sim.active else 20)
        for f in sim.tick(now):  # absolute clock, same as the real sources
            sink(f)
        await asyncio.sleep(1 / rate)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, sink: Sink, nodes: dict[str, str]):
        self.sink, self.nodes = sink, nodes

    def datagram_received(self, data: bytes, addr) -> None:
        node = self.nodes.get(addr[0], addr[0])
        for line in data.decode(errors="ignore").splitlines():
            f = parse_esp32_line(line, node, time.monotonic())
            if f:
                self.sink(f)


async def run_udp(sink: Sink, port: int, nodes: dict[str, str]) -> None:
    """Listen for esp-csi text lines sent by sniffer nodes (nodes: ip -> name)."""
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: _UdpProtocol(sink, nodes), local_addr=("0.0.0.0", port))
    await asyncio.Event().wait()


async def run_serial(sink: Sink, path: str, node: str, baud: int = 921600) -> None:
    """Read esp-csi output from a USB-attached ESP32."""
    import serial  # pyserial, optional

    ser = serial.Serial(path, baud, timeout=0)
    buf = b""
    while True:
        buf += ser.read(4096)
        *lines, buf = buf.split(b"\n")
        for line in lines:
            f = parse_esp32_line(line.decode(errors="ignore"), node, time.monotonic())
            if f:
                sink(f)
        await asyncio.sleep(0.005)
