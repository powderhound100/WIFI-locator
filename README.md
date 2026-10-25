# WiFi locator — see motion room by room with CSI

Turns WiFi channel state information (CSI, the per-subcarrier channel estimate)
into a live "is something moving here?" dashboard per area of the house.

```
python -m pip install -r requirements.txt
python -m wifi_locator --simulate          # no hardware; open http://127.0.0.1:8080
python -m wifi_locator --config config.json
python -m pytest
```

## The hardware catch

Your phones, laptops, TVs and router compute CSI internally but **do not expose
it**: stock firmware and OS drivers hide it. So "just use the devices I already
have" can't work by software alone. What *does* work:

- **Existing devices as transmitters, a small sniffer as receiver.** CSI can be
  extracted from *any* frame a CSI-capable radio overhears, so the sniffer
  doesn't need to join anything. Your existing devices' normal traffic becomes
  the signal source, and each link is `(sniffer node, transmitting MAC)`.
- **Sniffer options:** an ESP32 ($5-10, the `esp-csi` firmware; promiscuous
  mode with CSI callback) per area, or a Raspberry Pi 3B+/4/5 with the Nexmon
  CSI patch. One node per room or zone gives per-room resolution.
- **Quiet devices give sparse data.** A TV in standby sends little. Motion
  detection needs roughly 20+ frames/s per link, so favour chatty devices
  (the router, streaming boxes, smart speakers) or have the node ping the router.

I haven't tested against real ESP32 hardware in this session. The parser targets
the documented `CSI_DATA,...,"[i,q,...]"` line format from `esp-csi`; check your
firmware version's column layout if frames don't show up.

## How it works

| Stage | File | What it does |
|---|---|---|
| Parse | `wifi_locator/csi.py` | `CSI_DATA` line → per-subcarrier amplitude |
| Score | `wifi_locator/detector.py` | normalise each frame by its mean (cancels AGC/power jumps), take the std-dev of each subcarrier over a sliding window, average |
| Calibrate | same | first 30 s (or press *Recalibrate*) learns each link's empty-house score; threshold = mean + 5σ, with hysteresis |
| Zones | same | links roll up to the zone of their receiving node; zone level = worst link |
| Serve | `wifi_locator/server.py`, `static/index.html` | WebSocket push at 4 Hz |
| Sources | `wifi_locator/sources.py` | simulator, UDP, serial |

## Setting up real nodes

1. Flash each ESP32 with an `esp-csi` receiver build that prints CSI lines.
2. Copy `config.example.json` to `config.json`. For USB-connected nodes set
   `"serial"`; for networked nodes set `"ip"` and forward the lines as UDP to
   port 5005. Map each node to a `zone` name.
3. Start with the house still so calibration learns "empty", then walk around.

## Limits

- This detects *motion* near each node's links. It does not give coordinates.
  Locating someone more precisely needs multiple nodes and trained models.
- Pets, fans, and swaying curtains move the channel too. Raising `k` reduces false alarms.
- Sensing people in a home is privacy-sensitive; tell housemates and guests.
