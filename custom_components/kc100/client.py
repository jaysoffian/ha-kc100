"""Async client for TP-Link Kasa KC100 cameras.

The KC100 exposes a JSON-over-HTTPS control channel on port 10443 at the path
`/data/LINKIE.json`. Requests are:

    POST /data/LINKIE.json
    Content-Type: application/x-www-form-urlencoded; charset=utf-8
    Authorization: Basic base64(username:hex(md5(password_utf8)))
    body: content=<urlencode(base64(xor_encrypt(json)))>

Where `xor_encrypt` is the classic Kasa running-XOR cipher (key starts 0xAB,
then `key = previous_cipher_byte`). Responses use the same envelope in reverse.

The camera presents a 1024-bit RSA cert, so we need an SSL context with
SECLEVEL=0 and no verification.

Commands are `{module: {method: args}}` dicts. See MODULES/methods mapped from
the Kasa iPad app binary (IotSwiftSDK.framework).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import ssl
import urllib.parse
import uuid
from typing import Any, Literal

import aiohttp

_LOGGER = logging.getLogger(__name__)

OnOff = Literal["on", "off"]
Sensitivity = Literal["low", "medium", "high"]
Resolution = Literal["1080P", "720P", "360P"]
Quality = Literal["low", "medium", "high"]
Rotation = Literal[0, 180]
PowerFreq = Literal[50, 60]
NightVisionMode = Literal["auto", "day", "night"]


class KC100Error(Exception):
    """Base error for KC100 client."""


class KC100AuthError(KC100Error):
    """Authentication failed (HTTP 401)."""


class KC100ProtocolError(KC100Error):
    """Camera returned a non-zero err_code."""

    def __init__(
        self, module: str, method: str, err_code: int, payload: dict[str, Any]
    ) -> None:
        msg = payload.get("err_msg")
        detail = msg or payload
        super().__init__(f"{module}.{method} err_code={err_code}: {detail}")
        self.module = module
        self.method = method
        self.err_code = err_code
        self.err_msg = msg
        self.payload = payload


def _make_ssl_context() -> ssl.SSLContext:
    """SSL context that accepts the KC100's weak 1024-bit RSA cert."""
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _xor_encrypt(plaintext: bytes) -> bytes:
    key = 0xAB
    out = bytearray()
    for b in plaintext:
        key ^= b
        out.append(key)
    return bytes(out)


def _xor_decrypt(cipher: bytes) -> bytes:
    key = 0xAB
    out = bytearray()
    for b in cipher:
        out.append(key ^ b)
        key = b
    return bytes(out)


def _encode_body(command: dict[str, Any]) -> bytes:
    wrapped = {**command, "context": {"source": str(uuid.uuid4())}}
    enc = _xor_encrypt(json.dumps(wrapped).encode())
    body_val = urllib.parse.quote(base64.b64encode(enc).decode(), safe="")
    return f"content={body_val}".encode()


def _decode_body(raw: bytes) -> dict[str, Any]:
    text = raw.decode()
    if text.startswith("content="):
        b64 = urllib.parse.unquote(text[len("content=") :])
    else:
        b64 = text.strip()
    decrypted = _xor_decrypt(base64.b64decode(b64))
    return json.loads(decrypted.decode())


class KC100Client:
    """Async client for a single KC100 camera."""

    # Camera occasionally returns -40602 "Other error" for valid requests; retry once.
    _TRANSIENT_ERR_CODES = frozenset({-40602})

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: float = 8.0,
    ) -> None:
        self._host = host
        self._username = username
        self._pw_md5 = hashlib.md5(password.encode(), usedforsecurity=False).hexdigest()
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._external_session = session is not None
        self._session = session
        self._session_lock = asyncio.Lock()
        self._ssl = _make_ssl_context()
        self._url = f"https://{host}:10443/data/LINKIE.json"

    async def close(self) -> None:
        if self._session is not None and not self._external_session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> KC100Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is not None:
            return self._session
        async with self._session_lock:
            if self._session is None:
                # Use threaded resolver to avoid aiodns/aiohttp version mismatches.
                resolver = aiohttp.ThreadedResolver()
                # limit_per_host=1: the camera resets connections when multiple
                # SSL handshakes arrive concurrently, so queue all requests on
                # one socket.
                connector = aiohttp.TCPConnector(
                    ssl=self._ssl, resolver=resolver, limit_per_host=1
                )
                self._session = aiohttp.ClientSession(
                    connector=connector, timeout=self._timeout
                )
            return self._session

    async def send(self, command: dict[str, Any]) -> dict[str, Any]:
        """POST a raw `{module: {method: args}}` command, return the unwrapped response.

        Raises KC100ProtocolError if the response's err_code is non-zero.
        Automatically retries once on known-transient camera errors or on a
        ServerDisconnectedError (camera closes idle keep-alive sockets before
        we can send).
        """
        try:
            return await self._send_once(command)
        except KC100ProtocolError as e:
            if e.err_code in self._TRANSIENT_ERR_CODES:
                _LOGGER.debug(
                    "retrying after transient err %s: %s", e.err_code, e.err_msg
                )
                return await self._send_once(command)
            raise
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientConnectionError) as e:
            _LOGGER.debug("retrying after connection error: %s", e)
            return await self._send_once(command)

    async def _send_once(self, command: dict[str, Any]) -> dict[str, Any]:
        session = await self._ensure_session()
        body = _encode_body(command)
        auth = aiohttp.BasicAuth(self._username, self._pw_md5)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Accept": "*/*",
        }
        async with session.post(
            self._url, data=body, headers=headers, auth=auth, ssl=self._ssl
        ) as r:
            if r.status == 401:
                raise KC100AuthError("401 Unauthorized: wrong username/password")
            if r.status != 200:
                raise KC100Error(f"HTTP {r.status}")
            raw = await r.read()
        if not raw:
            raise KC100Error("empty response body")
        resp = _decode_body(raw)
        return self._unwrap(command, resp)

    @staticmethod
    def _unwrap(command: dict[str, Any], resp: dict[str, Any]) -> dict[str, Any]:
        """Extract the inner response, checking err_code."""
        module = next(iter(command))
        method = next(iter(command[module]))
        inner = resp.get(module)
        if not isinstance(inner, dict):
            snippet = str(resp)[:200]
            raise KC100Error(f"unexpected response shape: {snippet}")
        if "err_code" in inner:
            ec = inner["err_code"]
            if ec != 0:
                raise KC100ProtocolError(module, method, ec, inner)
            return inner
        mresp = inner.get(method)
        if not isinstance(mresp, dict):
            snippet = str(resp)[:200]
            raise KC100Error(f"unexpected response shape: {snippet}")
        ec = mresp.get("err_code", 0)
        if ec != 0:
            raise KC100ProtocolError(module, method, ec, mresp)
        return mresp

    # ---- Typed feature API -------------------------------------------------
    # Each pair is a simple `{module: {method: args}}` wrapper.

    async def _get(self, module: str, method: str) -> dict[str, Any]:
        return await self.send({module: {method: {}}})

    async def _set(
        self, module: str, method: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.send({module: {method: args}})

    # power (privacy switch: camera on/off)
    async def get_power(self) -> OnOff:
        return (await self._get("smartlife.cam.ipcamera.switch", "get_is_enable"))[
            "value"
        ]

    async def set_power(self, value: OnOff) -> None:
        await self._set(
            "smartlife.cam.ipcamera.switch", "set_is_enable", {"value": value}
        )

    # status LED
    async def get_led(self) -> OnOff:
        return (await self._get("smartlife.cam.ipcamera.led", "get_status"))["value"]

    async def set_led(self, value: OnOff) -> None:
        await self._set("smartlife.cam.ipcamera.led", "set_status", {"value": value})

    # motion detect
    async def get_motion_enabled(self) -> OnOff:
        return (
            await self._get("smartlife.cam.ipcamera.motionDetect", "get_is_enable")
        )["value"]

    async def set_motion_enabled(self, value: OnOff) -> None:
        await self._set(
            "smartlife.cam.ipcamera.motionDetect", "set_is_enable", {"value": value}
        )

    async def get_motion_sensitivity(self) -> Sensitivity:
        return (
            await self._get("smartlife.cam.ipcamera.motionDetect", "get_sensitivity")
        )["value"]

    async def set_motion_sensitivity(self, value: Sensitivity) -> None:
        await self._set(
            "smartlife.cam.ipcamera.motionDetect", "set_sensitivity", {"value": value}
        )

    async def get_motion_sensitivity_level(self) -> tuple[int, int]:
        r = await self._get(
            "smartlife.cam.ipcamera.motionDetect", "get_sensitivity_level"
        )
        return r["day_mode_level"], r["night_mode_level"]

    async def set_motion_sensitivity_level(self, day: int, night: int) -> None:
        await self._set(
            "smartlife.cam.ipcamera.motionDetect",
            "set_sensitivity_level",
            {"day_mode_level": day, "night_mode_level": night},
        )

    async def get_motion_min_trigger_time(self) -> tuple[int, int]:
        r = await self._get(
            "smartlife.cam.ipcamera.motionDetect", "get_min_trigger_time"
        )
        return r["day_mode_value"], r["night_mode_value"]

    async def set_motion_min_trigger_time(self, day_ms: int, night_ms: int) -> None:
        await self._set(
            "smartlife.cam.ipcamera.motionDetect",
            "set_min_trigger_time",
            {"day_mode_value": day_ms, "night_mode_value": night_ms},
        )

    async def get_motion_detect_area(self) -> dict[str, Any]:
        return await self._get("smartlife.cam.ipcamera.motionDetect", "get_detect_area")

    async def set_motion_detect_area(self, area: list[dict[str, list[int]]]) -> None:
        await self._set(
            "smartlife.cam.ipcamera.motionDetect", "set_detect_area", {"area": area}
        )

    # sound detect
    async def get_sound_enabled(self) -> OnOff:
        return (await self._get("smartlife.cam.ipcamera.soundDetect", "get_is_enable"))[
            "value"
        ]

    async def set_sound_enabled(self, value: OnOff) -> None:
        await self._set(
            "smartlife.cam.ipcamera.soundDetect", "set_is_enable", {"value": value}
        )

    async def get_sound_sensitivity(self) -> Sensitivity:
        return (
            await self._get("smartlife.cam.ipcamera.soundDetect", "get_sensitivity")
        )["value"]

    async def set_sound_sensitivity(self, value: Sensitivity) -> None:
        await self._set(
            "smartlife.cam.ipcamera.soundDetect", "set_sensitivity", {"value": value}
        )

    # video control
    async def get_resolution(self) -> Resolution:
        r = await self._get("smartlife.cam.ipcamera.videoControl", "get_resolution")
        return r["value"][0]["resolution"]

    async def set_resolution(self, value: Resolution, *, channel: int = 1) -> None:
        await self._set(
            "smartlife.cam.ipcamera.videoControl",
            "set_resolution",
            {"value": [{"channel": channel, "resolution": value}]},
        )

    async def get_channel_quality(self) -> Quality:
        r = await self._get(
            "smartlife.cam.ipcamera.videoControl", "get_channel_quality"
        )
        return r["value"][0]["quality"]

    async def set_channel_quality(self, value: Quality, *, channel: int = 1) -> None:
        await self._set(
            "smartlife.cam.ipcamera.videoControl",
            "set_channel_quality",
            {"value": [{"channel": channel, "quality": value}]},
        )

    async def get_rotation(self) -> int:
        return (
            await self._get(
                "smartlife.cam.ipcamera.videoControl", "get_rotation_degree"
            )
        )["value"]

    async def set_rotation(self, degrees: Rotation) -> None:
        await self._set(
            "smartlife.cam.ipcamera.videoControl",
            "set_rotation_degree",
            {"value": degrees},
        )

    async def get_power_frequency(self) -> int:
        return (
            await self._get(
                "smartlife.cam.ipcamera.videoControl", "get_power_frequency"
            )
        )["value"]

    async def set_power_frequency(self, hz: PowerFreq) -> None:
        await self._set(
            "smartlife.cam.ipcamera.videoControl", "set_power_frequency", {"value": hz}
        )

    # OSD
    async def get_osd_logo(self) -> OnOff:
        return (await self._get("smartlife.cam.ipcamera.OSD", "get_logo_is_enable"))[
            "value"
        ]

    async def set_osd_logo(self, value: OnOff) -> None:
        await self._set(
            "smartlife.cam.ipcamera.OSD", "set_logo_is_enable", {"value": value}
        )

    async def get_osd_time(self) -> OnOff:
        return (await self._get("smartlife.cam.ipcamera.OSD", "get_time_is_enable"))[
            "value"
        ]

    async def set_osd_time(self, value: OnOff) -> None:
        await self._set(
            "smartlife.cam.ipcamera.OSD", "set_time_is_enable", {"value": value}
        )

    # day/night (night vision)
    async def get_night_vision(self) -> NightVisionMode:
        return (await self._get("smartlife.cam.ipcamera.dayNight", "get_mode"))["value"]

    async def set_night_vision(self, value: NightVisionMode) -> None:
        await self._set("smartlife.cam.ipcamera.dayNight", "set_mode", {"value": value})

    # system / misc
    async def get_time(self) -> int:
        return (await self._get("smartlife.cam.ipcamera.dateTime", "get_time"))[
            "epoch_sec"
        ]

    async def get_cloud_info(self) -> dict[str, Any]:
        return await self._get("smartlife.cam.ipcamera.cloud", "get_info")
