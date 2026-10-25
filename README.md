# WiFi locator — see motion room by room with CSI

Turns WiFi channel state information (CSI, the per-subcarrier channel estimate)
into a live "is something moving here?" dashboard per area of the house.

```
python -m pip install -r requirements.txt
python -m wifi_locator --simulate          # no hardware; open http://127.0.0.1:8080
python -m wifi_locator --config config.json
python -m pytest
```

## Using the devices you already have

Be clear about what each device can do. **CSI** (per-subcarrier channel data) is
the best signal, but stock routers, PCs and smart TVs don't expose it. **RSSI**
(one signal-strength number per frame) is available on nearly everything, and is
what the zero-new-hardware modes below use. It is coarser: expect to detect
people moving through or near a link, not subtle motion.

| Device | Role | How |
|---|---|---|
| **Smart TVs, consoles, IoT** | Transmitter only. They can't run code, but any frame they send can be measured. | List their IPs under `"ping"` so they keep replying (~5 frames/s). |
| **Router running OpenWrt** | Receiver: signal strength of every connected client | `"openwrt_host"` node; polls `iw dev wlanX station dump` over SSH (key auth). Stock firmware won't do this; check whether your model supports OpenWrt. |
| **Linux PC with a monitor-mode adapter** | Receiver: overhears every device on the channel | `"monitor_iface"` node; needs `tshark`, root, and the adapter on your network's channel. Most USB adapters work; many built-in cards don't. |
| **Any PC** | Receiver of its own link to the router | Run `python -m wifi_locator.agent --server <dashboard-ip>` (Linux or Windows) and add the PC as an `"ip"` node. Windows reports 1% steps, so it's the coarsest. |
| **CSI-capable hardware** (optional upgrade) | Full CSI | ESP32 with `esp-csi`, Raspberry Pi/some Asus & Netgear routers with Nexmon CSI, Intel AX200/AX210 PCs with PicoScenes. Same dashboard, much better sensitivity. |

Each (receiver, transmitting device) pair is a link, and each node maps to a
zone. More links crossing a room means better coverage: put receivers in
different rooms rather than all in one.

**Not yet tested against real hardware** (no router, PC adapter or ESP32 in this
session). The parsers are covered by unit tests on sample lines, and the
detector by simulation. Expect to tune `k` and the window on your own network.

## How it works

| Stage | File | What it does |
|---|---|---|
| Parse | `wifi_locator/csi.py` | `CSI_DATA` line → per-subcarrier amplitude |
| Score | `wifi_locator/detector.py` | normalise each frame by its mean (cancels AGC/power jumps), take the std-dev of each subcarrier over a sliding window, average |
| Calibrate | same | first 30 s (or press *Recalibrate*) learns each link's empty-house score; threshold = mean + 5σ, with hysteresis |
| Zones | same | links roll up to the zone of their receiving node; zone level = worst link |
| Serve | `wifi_locator/server.py`, `static/index.html` | WebSocket push at 4 Hz |
| Sources | `wifi_locator/sources.py`, `agent.py` | simulator, UDP, serial, tshark monitor, OpenWrt SSH, pinger |

## Setting up

1. `cp config.example.json config.json`, then keep only the nodes you have.
2. Router: enable SSH key login from the dashboard machine, set `openwrt_host`.
3. Monitor PC: `sudo ip link set wlan1 down && sudo iw wlan1 set monitor none && sudo ip link set wlan1 up && sudo iw wlan1 set channel <your channel>`, then run the dashboard as root.
4. Start the dashboard with the house still so calibration learns "empty", then walk around.
5. ESP32 nodes (CSI): flash `esp-csi`, send lines over UDP to port 5005 or attach via `"serial"`.

## Limits

- This detects *motion* near each node's links. It does not give coordinates.
  Locating someone more precisely needs multiple nodes and trained models.
- RSSI mode is much noisier than CSI; walls between receiver and transmitter weaken both.
- Pets, fans, and swaying curtains move the channel too. Raising `k` reduces false alarms.
- Sensing people in a home is privacy-sensitive; tell housemates and guests.
