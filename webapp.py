#!/usr/bin/env -S uv run python
"""Mac-local webapp for controlling KC100 cameras.

A single-file FastAPI app with embedded HTML/JS. Serves a dashboard UI for
toggling camera features and a visual editor for motion-detection zones.

Usage:
    KASA_USERNAME=... KASA_PASSWORD=... ./webapp.py [--port 8000]

Cameras are read from `webapp.toml` at repo root:
    [[camera]]
    name = "Kitchen"
    host = "kc100-kitchen.lan"

If that file is missing, the UI falls back to `?host=<host>` in the URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from custom_components.kc100.client import KC100Client, KC100Error, KC100ProtocolError

_LOGGER = logging.getLogger("kc100.webapp")

REPO_ROOT = Path(__file__).resolve().parent
WEBAPP_TOML = REPO_ROOT / "webapp.toml"
SNAPSHOTS_DIR = REPO_ROOT / "webapp"
INDEX_HTML_PATH = REPO_ROOT / "webapp.html"

# feature -> (getter, setter)
FEATURES: dict[str, tuple[str, str]] = {
    "power": ("get_power", "set_power"),
    "led": ("get_led", "set_led"),
    "motion.enabled": ("get_motion_enabled", "set_motion_enabled"),
    "motion.sensitivity": ("get_motion_sensitivity", "set_motion_sensitivity"),
    "motion.sensitivity_level": (
        "get_motion_sensitivity_level",
        "set_motion_sensitivity_level",
    ),
    "motion.min_trigger_time": (
        "get_motion_min_trigger_time",
        "set_motion_min_trigger_time",
    ),
    "sound.enabled": ("get_sound_enabled", "set_sound_enabled"),
    "sound.sensitivity": ("get_sound_sensitivity", "set_sound_sensitivity"),
    "resolution": ("get_resolution", "set_resolution"),
    "quality": ("get_channel_quality", "set_channel_quality"),
    "rotation": ("get_rotation", "set_rotation"),
    "power_frequency": ("get_power_frequency", "set_power_frequency"),
    "osd.logo": ("get_osd_logo", "set_osd_logo"),
    "osd.time": ("get_osd_time", "set_osd_time"),
    "night_vision": ("get_night_vision", "set_night_vision"),
}

# read-only getters included in /api/state
READONLY_FEATURES: dict[str, str] = {
    "motion.detect_area": "get_motion_detect_area",
    "time": "get_time",
    "cloud_info": "get_cloud_info",
}


_clients: dict[str, KC100Client] = {}
_clients_lock = asyncio.Lock()
_credentials: list[tuple[str, str]] = []


def _load_cameras() -> list[dict[str, str]]:
    if not WEBAPP_TOML.exists():
        _LOGGER.info(
            "webapp.toml not found at %s; UI will prompt for ?host=... "
            "(see webapp.toml.example)",
            WEBAPP_TOML,
        )
        return []
    try:
        with WEBAPP_TOML.open("rb") as f:
            raw = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        _LOGGER.error("failed to read webapp.toml: %s", e)
        return []
    cameras: list[dict[str, str]] = []
    for entry in raw.get("camera", []):
        if not isinstance(entry, dict):
            _LOGGER.warning("skipping camera entry: not a table: %r", entry)
            continue
        if "name" not in entry:
            _LOGGER.warning("skipping camera entry: missing 'name': %r", entry)
            continue
        if "host" not in entry:
            _LOGGER.warning("skipping camera entry: missing 'host': %r", entry)
            continue
        cameras.append({"name": entry["name"], "host": entry["host"]})
    return cameras


async def _get_client(host: str) -> KC100Client:
    async with _clients_lock:
        c = _clients.get(host)
        if c is None:
            if not _credentials:
                raise RuntimeError("credentials not initialized")
            username, password = _credentials[0]
            c = KC100Client(host, username, password)
            _clients[host] = c
        return c


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    async with _clients_lock:
        for c in _clients.values():
            try:
                await c.close()
            except Exception as e:
                _LOGGER.warning("error closing client: %s", e)
        _clients.clear()


async def _aiohttp_error_handler(_req: Request, exc: Exception) -> Response:
    _LOGGER.warning("camera connection error (%s): %s", exc.__class__.__name__, exc)
    return JSONResponse(
        status_code=503,
        content={"error": f"camera unreachable: {exc.__class__.__name__}: {exc}"},
    )


async def _timeout_handler(_req: Request, exc: Exception) -> Response:
    _LOGGER.warning("camera timeout (%s): %s", exc.__class__.__name__, exc)
    return JSONResponse(
        status_code=503,
        content={"error": f"camera timeout: {exc.__class__.__name__}: {exc}"},
    )


async def _kc100_protocol_handler(_req: Request, exc: Exception) -> Response:
    assert isinstance(exc, KC100ProtocolError)
    _LOGGER.error("protocol error: %s", exc)
    return JSONResponse(
        status_code=400,
        content={"error": str(exc), "err_code": exc.err_code, "err_msg": exc.err_msg},
    )


async def _kc100_error_handler(_req: Request, exc: Exception) -> Response:
    _LOGGER.error("camera error: %s", exc)
    return JSONResponse(status_code=502, content={"error": str(exc)})


app = FastAPI(lifespan=_lifespan)
app.add_exception_handler(aiohttp.ClientError, _aiohttp_error_handler)
app.add_exception_handler(TimeoutError, _timeout_handler)
app.add_exception_handler(KC100ProtocolError, _kc100_protocol_handler)
app.add_exception_handler(KC100Error, _kc100_error_handler)


# Hostnames (RFC 1123) and IPv4 literals - no path separators, no `..`, etc.
# IPv6 (bracketed or bare) is not supported; extend this regex if needed.
_HOST_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?"
_HOST_RE = re.compile(rf"^(?=.{{1,253}}$){_HOST_LABEL}(\.{_HOST_LABEL})*$")


def _require_host(host: str | None) -> str:
    if not host:
        raise HTTPException(status_code=400, detail="missing host")
    if not _HOST_RE.match(host):
        raise HTTPException(status_code=400, detail=f"invalid host: {host}")
    return host


async def _call_getter(client: KC100Client, getter: str) -> Any:
    val = await getattr(client, getter)()
    # normalize tuples to lists for JSON
    if isinstance(val, tuple):
        return list(val)
    if getter == "get_motion_detect_area" and isinstance(val, dict):
        return {k: v for k, v in val.items() if k != "err_code"}
    return val


@app.get("/api/cameras")
async def api_cameras() -> list[dict[str, str]]:
    return _load_cameras()


@app.get("/api/state")
async def api_state(host: str | None = None) -> dict[str, Any]:
    host = _require_host(host)
    client = await _get_client(host)

    all_features: list[tuple[str, str]] = [
        (name, getter) for name, (getter, _) in FEATURES.items()
    ] + list(READONLY_FEATURES.items())

    async def _safe(getter: str) -> Any:
        try:
            return await _call_getter(client, getter)
        except KC100ProtocolError as e:
            return {"error": str(e), "err_code": e.err_code, "err_msg": e.err_msg}
        except KC100Error as e:
            return {"error": str(e)}

    # Serial, not asyncio.gather: the camera resets concurrent SSL handshakes.
    results = [await _safe(g) for _, g in all_features]
    return dict(zip((n for n, _ in all_features), results, strict=True))


@app.post("/api/set")
async def api_set(request: Request) -> dict[str, Any]:
    body = await request.json()
    host = _require_host(body.get("host"))
    feature = body.get("feature")
    args = body.get("args") or []
    if not isinstance(args, list):
        raise HTTPException(status_code=400, detail="args must be a list")
    if feature not in FEATURES:
        raise HTTPException(status_code=400, detail=f"unknown feature: {feature}")
    getter, setter = FEATURES[feature]
    client = await _get_client(host)
    await getattr(client, setter)(*args)
    val = await _call_getter(client, getter)
    return {"ok": True, "value": val}


@app.get("/api/zones")
async def api_zones_get(host: str | None = None) -> dict[str, Any]:
    host = _require_host(host)
    client = await _get_client(host)
    area = await client.get_motion_detect_area()
    return {k: v for k, v in area.items() if k != "err_code"}


@app.put("/api/zones")
async def api_zones_put(request: Request, host: str | None = None) -> dict[str, Any]:
    host = _require_host(host)
    body = await request.json()
    area = body.get("area")
    if not isinstance(area, list):
        raise HTTPException(status_code=400, detail="body must be {area: [...]}")
    _LOGGER.info("set_motion_detect_area(%s): %s", host, json.dumps(area))
    client = await _get_client(host)
    await client.set_motion_detect_area(area)
    fresh = await client.get_motion_detect_area()
    return {"ok": True, "area": {k: v for k, v in fresh.items() if k != "err_code"}}


def _snapshot_path(host: str) -> Path:
    # host has already passed _require_host's regex (no path separators).
    return SNAPSHOTS_DIR / f"{host}.jpg"


# sanity cap only; snapshots are small JPEGs in practice.
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


@app.post("/api/snapshot")
async def api_snapshot_post(
    file: UploadFile, host: str | None = None
) -> dict[str, Any]:
    host = _require_host(host)
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    data = await file.read(MAX_SNAPSHOT_BYTES + 1)
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(status_code=413, detail="snapshot too large")
    _snapshot_path(host).write_bytes(data)
    return {"ok": True, "bytes": len(data)}


@app.get("/api/snapshot")
async def api_snapshot_get(host: str | None = None) -> FileResponse:
    host = _require_host(host)
    p = _snapshot_path(host)
    if not p.exists():
        raise HTTPException(status_code=404, detail="no snapshot")
    return FileResponse(p, media_type="image/jpeg")


@app.delete("/api/snapshot")
async def api_snapshot_delete(host: str | None = None) -> dict[str, Any]:
    host = _require_host(host)
    p = _snapshot_path(host)
    if p.exists():
        p.unlink()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML_PATH.read_text()


def _main() -> None:
    parser = argparse.ArgumentParser(description="KC100 webapp")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not os.environ.get("KASA_USERNAME") or not os.environ.get("KASA_PASSWORD"):
        print("error: set KASA_USERNAME and KASA_PASSWORD", file=sys.stderr)
        sys.exit(2)

    _credentials[:] = [(os.environ["KASA_USERNAME"], os.environ["KASA_PASSWORD"])]

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    _main()
