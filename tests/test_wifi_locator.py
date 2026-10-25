import numpy as np

from wifi_locator.csi import parse_esp32_line
from wifi_locator.detector import MotionEngine
from wifi_locator.sources import Simulator

TX = "aa:00:00:00:00:01"


def run(engine, sim, t0, t1, rate=40):
    for t in np.arange(t0, t1, 1 / rate):
        for f in sim.tick(float(t)):
            engine.feed(f)
    return t1


def test_parse_esp32_line():
    line = 'CSI_DATA,1,AA:BB:CC:DD:EE:FF,-40,11,1,0,0,0,0,0,0,0,0,-90,0,6,2,123,0,0,0,8,0,"[3,4,0,5,6,8,0,0]"'
    f = parse_esp32_line(line, "n1", 1.0)
    assert f.tx == "aa:bb:cc:dd:ee:ff" and f.rssi == -40
    assert f.amp.tolist() == [5.0, 5.0, 10.0, 0.0]


def test_parse_rejects_garbage():
    assert parse_esp32_line("I (123) wifi: hello", "n", 0) is None
    assert parse_esp32_line('CSI_DATA,1,mac,-40,"[1,2,3]"', "n", 0) is None


def test_detects_motion_only_in_the_active_zone():
    sim = Simulator({"a": [TX], "b": [TX]}, seed=1)
    eng = MotionEngine(zones={"a": "Kitchen", "b": "Bedroom"}, calib_seconds=10)
    t = run(eng, sim, 0, 12)
    assert not eng.calibrating

    t = run(eng, sim, t, t + 5)  # still: no false alarms
    assert not any(z["moving"] for z in eng.snapshot(t)["zones"].values())

    sim.active = {"a"}
    t = run(eng, sim, t, t + 5)
    zones = eng.snapshot(t)["zones"]
    assert zones["Kitchen"]["moving"] and not zones["Bedroom"]["moving"]

    sim.active = set()
    t = run(eng, sim, t, t + 5)
    assert not eng.snapshot(t)["zones"]["Kitchen"]["moving"]


def test_recalibrate_resets_state():
    sim = Simulator({"a": [TX]}, seed=2)
    eng = MotionEngine(calib_seconds=5)
    t = run(eng, sim, 0, 7)
    eng.calibrate()
    assert eng.calibrating and eng.snapshot(t)["zones"]["a"]["level"] == 0


def test_parse_rssi_and_tshark_lines():
    from wifi_locator.csi import parse_rssi_line, parse_tshark_line

    f = parse_rssi_line("RSSI,AA:BB:CC:DD:EE:FF,-52.0", "pc1", 1.0)
    assert f.tx == "aa:bb:cc:dd:ee:ff" and f.rssi == -52 and f.amp.size == 1
    g = parse_tshark_line("aa:bb:cc:dd:ee:01\t-61,-63\n", "mon", 1.0)
    assert g.rssi == -61
    assert parse_tshark_line("\t-61\n", "mon", 1.0) is None
    assert parse_rssi_line("garbage", "n", 0) is None


def test_rssi_links_detect_motion():
    from wifi_locator.csi import rssi_frame

    rng = np.random.default_rng(0)
    eng = MotionEngine(calib_seconds=20)
    t = 0.0

    def feed(seconds, swing):
        nonlocal t
        for _ in range(int(seconds * 10)):
            t += 0.1
            eng.feed(rssi_frame("router", "aa:00:00:00:00:09", t, -50 + rng.normal(0, 0.4) + rng.normal(0, swing)))

    feed(22, 0)
    assert not eng.calibrating
    feed(8, 0)
    assert not eng.snapshot(t)["zones"]["router"]["moving"]
    feed(8, 4)  # a person walking through the path swings RSSI by several dB
    assert eng.snapshot(t)["zones"]["router"]["moving"]
