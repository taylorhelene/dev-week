import asyncio
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

IDLE_SECONDS = int(os.getenv("IDLE_SECONDS", "300"))
REPEAT_SECONDS = int(os.getenv("REPEAT_SECONDS", "1800"))
QEMU_SERIAL = os.getenv("QEMU_SERIAL", "1").lower() in {"1", "true", "yes"}
SERIAL_HOST = os.getenv("SERIAL_HOST", "127.0.0.1")
SERIAL_PORT = int(os.getenv("SERIAL_PORT", "5678"))

app = FastAPI(title="Movement Reminder")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

last_movement = time.monotonic()
last_alert = 0.0
alert_number = 0
events = deque(maxlen=50)
serial_connected = False
serial_writer = None


def record_movement(source: str) -> None:
    """Record movement and restart the inactivity timer."""
    global last_movement

    last_movement = time.monotonic()
    events.appendleft({
        "time": datetime.now(timezone.utc).isoformat(),
        "message": "Movement detected",
        "source": source,
    })


def get_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


async def serial_reader() -> None:
    """Connect to QEMU's TCP serial port and listen for firmware messages."""
    global serial_connected, serial_writer

    while True:
        try:
            reader, writer = await asyncio.open_connection(SERIAL_HOST, SERIAL_PORT)
            serial_writer = writer
            serial_connected = True
            events.appendleft({
                "time": datetime.now(timezone.utc).isoformat(),
                "message": "QEMU serial connected",
                "source": "QEMU",
            })

            while line := await reader.readline():
                message = line.decode("utf-8", errors="replace").strip()
                if message == "MOVEMENT":
                    record_movement("QEMU simulated event")
                elif message:
                    events.appendleft({
                        "time": datetime.now(timezone.utc).isoformat(),
                        "message": message,
                        "source": "QEMU",
                    })

            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            serial_writer = None
            serial_connected = False

        await asyncio.sleep(3)


@app.on_event("startup")
async def start_serial_listener() -> None:
    if QEMU_SERIAL:
        asyncio.create_task(serial_reader())


@app.get("/")
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def health():
    return {"ok": True}


@app.get("/api/status")
async def status(tz: str = Query(default="UTC")):
    global alert_number, last_alert

    zone = get_zone(tz)
    local_now = datetime.now(zone)
    now_mono = time.monotonic()
    idle_for = int(now_mono - last_movement)

    within_hours = 8 <= local_now.hour < 22
    due = (
        within_hours
        and idle_for >= IDLE_SECONDS
        and (
            last_alert == 0.0
            or now_mono - last_alert >= REPEAT_SECONDS
        )
    )

    if due:
        alert_number += 1
        last_alert = now_mono
        events.appendleft({
            "time": datetime.now(timezone.utc).isoformat(),
            "message": "Inactivity reminder",
            "source": "Reminder",
        })

    return {
        "local_time": local_now.isoformat(),
        "timezone": str(zone),
        "within_hours": within_hours,
        "idle_seconds": idle_for,
        "idle_threshold_seconds": IDLE_SECONDS,
        "serial_connected": serial_connected,
        "alert_number": alert_number,
        "events": list(events),
    }


@app.post("/api/simulate-movement")
async def simulate_movement():
    if serial_writer is not None and not serial_writer.is_closing():
        serial_writer.write(b"M\n")
        await serial_writer.drain()
        return {"sent_to_qemu": True, "message": "Movement command sent to QEMU"}

    record_movement("Web test button")
    return {"sent_to_qemu": False, "message": "Movement simulated by the web app"}
