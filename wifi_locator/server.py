"""Web dashboard: serves a static page and pushes zone state over a WebSocket."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from .detector import MotionEngine

STATIC = Path(__file__).parent / "static"


def make_app(engine: MotionEngine, sources: list, push_hz: float = 4.0) -> web.Application:
    app = web.Application()
    app["clients"] = set()

    async def index(_):
        return web.FileResponse(STATIC / "index.html")

    async def ws(request):
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        request.app["clients"].add(sock)
        try:
            async for msg in sock:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            request.app["clients"].discard(sock)
        return sock

    async def calibrate(_):
        engine.calibrate()
        return web.json_response({"ok": True})

    async def state(_):
        return web.json_response(engine.snapshot(time.monotonic()))

    async def broadcaster(app):
        while True:
            snap = engine.snapshot(time.monotonic())
            for c in list(app["clients"]):
                try:
                    await c.send_json(snap)
                except ConnectionError:
                    app["clients"].discard(c)
            await asyncio.sleep(1 / push_hz)

    async def start(app):
        app["tasks"] = [asyncio.create_task(broadcaster(app))]
        app["tasks"] += [asyncio.create_task(s) for s in sources]

    async def stop(app):
        for t in app["tasks"]:
            t.cancel()

    app.router.add_get("/", index)
    app.router.add_get("/ws", ws)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/calibrate", calibrate)
    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    return app
