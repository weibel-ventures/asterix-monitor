# ASTERIX Debug Monitor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A single-container debug tool that receives ASTERIX UDP messages and displays them in a Wireshark-style web UI so engineers can verify messages reach the server.

**Architecture:** Single Python asyncio process running a UDP listener and FastAPI server. Messages are parsed with `asterix-decoder` and stored in an in-memory ring buffer. A WebSocket pushes the full buffer on connect and streams new messages in real-time. The frontend is a single HTML file with a three-pane Wireshark-style layout.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, asterix-decoder, websockets, vanilla JS/CSS

---

### Task 1: Project scaffold and dependencies

**Files:**
- Create: `app/__init__.py`
- Create: `app/main.py` (stub)
- Create: `app/static/index.html` (stub)
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Step 1: Create requirements.txt**

```
fastapi>=0.110
uvicorn[standard]>=0.29
websockets>=12.0
asterix-decoder>=0.7.11
```

**Step 2: Create minimal app/main.py**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(title="ASTERIX Monitor")
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

**Step 3: Create stub app/static/index.html**

```html
<!DOCTYPE html>
<html><head><title>ASTERIX Monitor</title></head>
<body><h1>ASTERIX Monitor</h1></body></html>
```

**Step 4: Create Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /opt/asterix-monitor
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
ENV ASTERIX_UDP_PORT=23401
ENV WEB_PORT=8080
ENV BUFFER_MAX_MESSAGES=50000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${WEB_PORT}
```

**Step 5: Create docker-compose.yml**

```yaml
services:
  monitor:
    build: .
    ports:
      - "${WEB_PORT:-8080}:${WEB_PORT:-8080}"
      - "${ASTERIX_UDP_PORT:-23401}:${ASTERIX_UDP_PORT:-23401}/udp"
    environment:
      - ASTERIX_UDP_PORT=${ASTERIX_UDP_PORT:-23401}
      - WEB_PORT=${WEB_PORT:-8080}
      - BUFFER_MAX_MESSAGES=${BUFFER_MAX_MESSAGES:-50000}
```

**Step 6: Verify Docker build**

```bash
docker compose build
```

**Step 7: Commit**

```bash
git add app/ requirements.txt Dockerfile docker-compose.yml
git commit -m "feat: project scaffold with FastAPI, Docker, and deps"
```

---

### Task 2: Ring buffer and UDP listener

**Files:**
- Modify: `app/main.py`

**Step 1: Implement ring buffer and UDP protocol**

The ring buffer is a `collections.deque(maxlen=N)` holding dataclass entries.
The UDP protocol calls `asterix.parse()` on each datagram, stores parsed + raw, and notifies WebSocket clients.

Key data model:
```python
@dataclass
class AsterixMessage:
    seq: int
    ts: float           # time.time()
    src_ip: str
    src_port: int
    raw: bytes
    parsed: list | None  # list of dicts from asterix.parse()
    parse_error: str | None
    size: int
```

FastAPI lifespan starts the UDP endpoint on `ASTERIX_UDP_PORT`.

**Step 2: Verify with replayer**

```bash
docker compose up -d
cd xenta-replayer && python3 replayer/pcap_replayer.py samples/weibel/2022_06_01_oslo.pcap 127.0.0.1 23401 1
# Observe log output showing messages received
docker compose logs -f
```

**Step 3: Commit**

```bash
git commit -am "feat: ring buffer and UDP listener with ASTERIX parsing"
```

---

### Task 3: WebSocket endpoint

**Files:**
- Modify: `app/main.py`

**Step 1: Add WebSocket /ws endpoint**

On connect: serialize full buffer as JSON snapshot, send.
On new UDP message: broadcast to all connected clients.

Serialization: each message becomes:
```json
{
  "seq": 1, "ts": 1711540981.23, "src_ip": "10.0.1.5", "src_port": 4820,
  "raw_hex": "300030fd...", "parsed": [...], "parse_error": null, "size": 45
}
```

**Step 2: Add /api/stats endpoint**

Returns `{"total_messages": N, "buffer_size": N, "connected_clients": N, "messages_per_sec": float}`.

**Step 3: Verify with wscat or browser console**

```bash
# In browser console: new WebSocket("ws://localhost:8080/ws")
```

**Step 4: Commit**

```bash
git commit -am "feat: WebSocket live stream and stats API"
```

---

### Task 4: Frontend — Wireshark-style three-pane UI

**Files:**
- Rewrite: `app/static/index.html`

**Step 1: Build the complete single-file HTML/JS/CSS UI**

Layout: header bar, filter bar, message list (top pane), decoded tree (bottom-left), hex dump (bottom-right).

Key behaviors:
- WebSocket connects on load, receives snapshot then live stream
- Message list: virtual-scroll-aware (render only visible rows for performance)
- Click row → show decoded tree + hex in bottom panes
- Auto-scroll when at bottom, pause when user scrolls up
- Filters: category dropdown, source IP dropdown, time range, text search
- All filter state in URL hash — shareable
- Message rate counter updated every second
- Pause/resume toggle
- Summary column shows: target ID (I240.TId), track number (I161.Tn), message type (I000.MsgTyp), or category number
- Decoded tree: collapsible nodes for each I### data item, showing desc + val + meaning
- Hex dump: classic 16-bytes-per-line with ASCII sidebar

**Step 2: Verify end-to-end with replayer**

```bash
docker compose up -d --build
cd xenta-replayer && python3 replayer/pcap_replayer.py samples/weibel/2022_06_01_oslo.pcap 127.0.0.1 23401 1
# Open http://localhost:8080 — should see messages scrolling
```

**Step 3: Commit**

```bash
git commit -am "feat: Wireshark-style three-pane ASTERIX monitor UI"
```

---

### Task 5: End-to-end verification and polish

**Step 1: Full integration test**

1. `docker compose up -d --build`
2. Run replayer against port 23401
3. Open browser to http://localhost:8080
4. Verify: messages appear and scroll
5. Verify: clicking a message shows decoded tree + hex
6. Verify: category filter works
7. Verify: IP filter works
8. Verify: text search works
9. Verify: URL hash updates and is restorable
10. Verify: pause/resume works

**Step 2: Commit final state**

```bash
git commit -am "feat: ASTERIX debug monitor v1 complete"
```
