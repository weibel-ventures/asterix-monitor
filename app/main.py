"""ASTERIX Debug Monitor — single-process FastAPI + UDP listener."""

import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asterix
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("asterix-monitor")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ASTERIX_UDP_PORT = int(os.environ.get("ASTERIX_UDP_PORT", "23401"))
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
BUFFER_MAX_MESSAGES = int(os.environ.get("BUFFER_MAX_MESSAGES", "50000"))

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AsterixEntry:
    seq: int
    ts: float
    src_ip: str
    src_port: int
    raw_hex: str
    parsed: list[dict[str, Any]] | None
    parse_error: str | None
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "src_ip": self.src_ip,
            "src_port": self.src_port,
            "raw_hex": self.raw_hex,
            "parsed": self.parsed,
            "parse_error": self.parse_error,
            "size": self.size,
        }


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------

class RingBuffer:
    def __init__(self, maxlen: int = BUFFER_MAX_MESSAGES):
        self._buf: deque[AsterixEntry] = deque(maxlen=maxlen)
        self._seq = 0
        self._rate_counter = 0
        self._rate_ts = time.monotonic()
        self._rate_value = 0.0

    def append(self, entry: AsterixEntry) -> None:
        self._buf.append(entry)
        self._rate_counter += 1

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def snapshot(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._buf]

    def update_rate(self) -> float:
        now = time.monotonic()
        dt = now - self._rate_ts
        if dt >= 1.0:
            self._rate_value = self._rate_counter / dt
            self._rate_counter = 0
            self._rate_ts = now
        return self._rate_value

    @property
    def rate(self) -> float:
        return self._rate_value

    def __len__(self) -> int:
        return len(self._buf)


buffer = RingBuffer()

# ---------------------------------------------------------------------------
# WebSocket manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        log.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        log.info("WebSocket client disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# UDP protocol
# ---------------------------------------------------------------------------

class AsterixUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        log.info("UDP listener ready on port %d", ASTERIX_UDP_PORT)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        ts = time.time()
        src_ip, src_port = addr[0], addr[1]
        raw_hex = data.hex()

        # Parse ASTERIX
        parsed = None
        parse_error = None
        try:
            parsed = asterix.parse(data)
        except Exception as exc:
            parse_error = str(exc)

        entry = AsterixEntry(
            seq=buffer.next_seq(),
            ts=ts,
            src_ip=src_ip,
            src_port=src_port,
            raw_hex=raw_hex,
            parsed=parsed,
            parse_error=parse_error,
            size=len(data),
        )
        buffer.append(entry)

        # Broadcast to WebSocket clients
        msg = json.dumps({"type": "new", "messages": [entry.to_dict()]}, default=str)
        asyncio.ensure_future(manager.broadcast(msg))

    def error_received(self, exc: Exception) -> None:
        log.warning("UDP error: %s", exc)


# ---------------------------------------------------------------------------
# Rate updater background task
# ---------------------------------------------------------------------------

async def rate_updater():
    while True:
        buffer.update_rate()
        await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

    # Start UDP listener
    transport, _ = await loop.create_datagram_endpoint(
        lambda: AsterixUDPProtocol(loop),
        local_addr=("0.0.0.0", ASTERIX_UDP_PORT),
    )
    log.info("ASTERIX UDP listener started on 0.0.0.0:%d", ASTERIX_UDP_PORT)

    # Start rate updater
    rate_task = asyncio.create_task(rate_updater())

    yield

    rate_task.cancel()
    transport.close()
    log.info("Shutting down")


app = FastAPI(title="ASTERIX Monitor", lifespan=lifespan)


# Serve the HTML UI at root
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text())


@app.get("/api/stats")
async def stats():
    return {
        "total_messages": buffer._seq,
        "buffer_size": len(buffer),
        "buffer_max": BUFFER_MAX_MESSAGES,
        "connected_clients": manager.count,
        "messages_per_sec": round(buffer.rate, 1),
        "udp_port": ASTERIX_UDP_PORT,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send full buffer snapshot on connect
        snapshot = buffer.snapshot()
        await ws.send_text(json.dumps({"type": "snapshot", "messages": snapshot}, default=str))

        # Keep connection alive — client doesn't send anything meaningful
        while True:
            # Wait for client pings / keep-alive
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
