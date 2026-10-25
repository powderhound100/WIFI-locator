"""Motion detection from per-link CSI amplitude variability.

Each (receiver node, transmitting MAC) pair is a link. A person moving
through the link's Fresnel zone perturbs multipath, so per-subcarrier
amplitude fluctuates over time. We score that fluctuation, learn what
"empty" looks like per link during calibration, and report each link's
score relative to its own threshold. Links roll up into zones.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .csi import CsiFrame

STALE_AFTER = 3.0  # seconds without frames before a link is offline


class LinkScorer:
    """Sliding-window amplitude variability for one link."""

    def __init__(self, window: int = 50, stride: int = 10):
        self.window, self.stride = window, stride
        self._buf: deque[np.ndarray] = deque(maxlen=window)
        self._since = 0

    def push(self, amp: np.ndarray) -> float | None:
        if self._buf and amp.shape != self._buf[0].shape:
            self._buf.clear()  # mode change (e.g. HT20 -> legacy)
        mean = amp.mean()
        if mean <= 0:
            return None
        # dividing by the frame mean cancels AGC / transmit-power jumps
        self._buf.append(amp / mean)
        self._since += 1
        if len(self._buf) < self.window or self._since < self.stride:
            return None
        self._since = 0
        m = np.stack(self._buf)
        live = m.mean(axis=0) > 0.05  # skip null/guard subcarriers
        if not live.any():
            return None
        return float(m[:, live].std(axis=0).mean())


@dataclass
class LinkState:
    node: str
    tx: str
    scorer: LinkScorer
    score: float = 0.0
    threshold: float | None = None
    moving: bool = False
    last_ts: float = 0.0
    rssi: int = 0
    calib: list[float] = field(default_factory=list)

    @property
    def level(self) -> float:
        """Score as a multiple of the link's motion threshold (>1 = motion)."""
        return self.score / self.threshold if self.threshold else 0.0


class MotionEngine:
    def __init__(
        self,
        zones: dict[str, str] | None = None,
        window: int = 50,
        stride: int = 10,
        calib_seconds: float = 30.0,
        k: float = 5.0,
        smoothing: float = 0.5,
    ):
        self.zone_of = zones if zones is not None else {}
        self.window, self.stride = window, stride
        self.calib_seconds, self.k, self.smoothing = calib_seconds, k, smoothing
        self.links: dict[tuple[str, str], LinkState] = {}
        self._calib_start: float | None = None
        self.calibrating = True

    def calibrate(self) -> None:
        """Restart calibration. The house should be still (empty) meanwhile."""
        self.calibrating = True
        self._calib_start = None
        for ls in self.links.values():
            ls.calib.clear()
            ls.threshold, ls.moving, ls.score = None, False, 0.0

    def feed(self, f: CsiFrame) -> None:
        ls = self.links.get((f.node, f.tx))
        if ls is None:
            ls = self.links[(f.node, f.tx)] = LinkState(
                f.node, f.tx, LinkScorer(self.window, self.stride)
            )
        ls.last_ts, ls.rssi = f.ts, f.rssi
        raw = ls.scorer.push(f.amp)
        if raw is None:
            return
        if self.calibrating:
            if self._calib_start is None:
                self._calib_start = f.ts
            ls.calib.append(raw)
            if f.ts - self._calib_start >= self.calib_seconds:
                self._finish_calibration()
            return
        if ls.threshold is None:  # link appeared after calibration
            ls.calib.append(raw)
            if len(ls.calib) >= 20:
                self._set_threshold(ls)
            return
        ls.score += self.smoothing * (raw - ls.score)
        # hysteresis: enter above threshold, leave below 80% of it
        ls.moving = ls.score > ls.threshold * (0.8 if ls.moving else 1.0)

    def _set_threshold(self, ls: LinkState) -> None:
        c = np.asarray(ls.calib)
        mean, std = c.mean(), c.std()
        ls.threshold = float(max(mean + self.k * std, mean * 1.3, mean + 1e-3))
        ls.score = float(mean)

    def _finish_calibration(self) -> None:
        for ls in self.links.values():
            if len(ls.calib) >= 5:
                self._set_threshold(ls)
        self.calibrating = False

    def snapshot(self, now: float) -> dict:
        zones: dict[str, dict] = {}
        links = []
        for ls in self.links.values():
            online = now - ls.last_ts < STALE_AFTER
            zone = self.zone_of.get(ls.node, ls.node)
            links.append(
                {
                    "node": ls.node,
                    "tx": ls.tx,
                    "zone": zone,
                    "online": online,
                    "rssi": ls.rssi,
                    "level": round(ls.level, 2),
                    "moving": bool(ls.moving and online),
                }
            )
            z = zones.setdefault(zone, {"level": 0.0, "moving": False, "links": 0})
            z["links"] += 1
            if online:
                z["level"] = max(z["level"], round(ls.level, 2))
                z["moving"] = z["moving"] or ls.moving
        return {"calibrating": self.calibrating, "zones": zones, "links": links}
