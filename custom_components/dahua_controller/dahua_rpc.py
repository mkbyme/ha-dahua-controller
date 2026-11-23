"""Dahua JSON-RPC ("RPC2") client over two transports.

The same JSON-RPC method set the camera's own web UI uses is reachable two ways:

* **HTTP, the camera's web port (80)** - `POST /RPC2_Login` then `POST /RPC2`.
* **DHIP, TCP 37777** - Dahua's private port. Besides the legacy binary
  protocol `DahuaNetSDKTalk` speaks, the same port also accepts JSON-RPC
  envelopes framed with a 32-byte "DHIP" header (what DMSS / Dahua's own
  tools send). Useful when the web port's RPC2 endpoint is disabled,
  firewalled, or answers differently.

Why this exists: `ptz.cgi` has no documented PTZ self-check / "PTZ Restart"
code (DAHUA HTTP API for IPC v1.40 §7.2.3 lists `Reset` = restore PTZ default
config and `PositionReset` = re-base zero on the current direction, both
harmful for drift). The web UI's "PTZ Restart" button calls the RPC method
`ptz.restartPtz` on a `ptz.factory.instance` object instead.

References (not verified against this project's hardware yet):
- DHIP header / two-stage login hash: rroller/dahua `vto.py`/`dhip.py`,
  mcw0/DahuaConsole `net.py`.
- RPC login + `ptz.factory.instance` + `object` field: rroller/dahua `rpc2.py`.
- `ptz.restartPtz`, `ptz.setPreset`: H3xano/dahua-rpc-api
  `modules/04-ptz-lens.md` (reverse-engineered from firmware web JS).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import struct
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DHIP_PORT = 37777
_DHIP_MAGIC = b"\x20\x00\x00\x00DHIP"
_DHIP_HEADER_SIZE = 32
_DHIP_MAX_BODY = 1024 * 1024
_LOGIN_CHALLENGE_CODE = 268632079  # "Component error: login challenge!"


class DahuaRpcError(Exception):
    """RPC call failed (transport error, refused login, or result=false)."""


def _rpc_password_hash(username: str, password: str, realm: str, random_: str) -> str:
    """Dahua 'Default' RPC login hash: MD5(user:random:MD5(user:realm:pass)), upper hex."""
    h1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest().upper()
    return hashlib.md5(f"{username}:{random_}:{h1}".encode()).hexdigest().upper()


def _describe_error(resp: dict) -> str:
    err = resp.get("error") or {}
    if isinstance(err, dict) and err:
        return f"code={err.get('code')} message={err.get('message')}"
    return "result=false"


class _DahuaRpcBase:
    """Transport-agnostic login / call / PTZ-object handling."""

    transport_name = "rpc"

    def __init__(self, username: str, password: str, timeout: float = 8.0) -> None:
        self._username = username
        self._password = password
        self._timeout = timeout
        self._id = 0
        self._session: Any = 0

    # Subclasses implement one raw request/response exchange.
    async def _exchange(self, message: dict, login: bool = False) -> dict:
        raise NotImplementedError

    async def _connect(self) -> None:
        """Open the underlying transport (no-op for HTTP)."""

    async def close(self) -> None:
        """Log out (best effort) and drop the transport."""

    async def call(
        self,
        method: str,
        params: Any = None,
        object_id: int | None = None,
        *,
        check: bool = True,
    ) -> dict:
        self._id += 1
        message: dict[str, Any] = {"method": method, "params": params, "id": self._id}
        if object_id:
            message["object"] = object_id
        if self._session:
            message["session"] = self._session
        resp = await self._exchange(message)
        if check and resp.get("result") is False:
            raise DahuaRpcError(f"{method} refused: {_describe_error(resp)}")
        return resp

    async def login(self) -> None:
        await self._connect()
        self._session = 0
        base = {"userName": self._username, "password": "", "clientType": "Web3.0", "loginType": "Direct"}
        self._id += 1
        challenge = await self._exchange(
            {"method": "global.login", "params": base, "id": self._id}, login=True
        )
        params = challenge.get("params") or {}
        realm, random_ = params.get("realm"), params.get("random")
        if not realm or not random_:
            raise DahuaRpcError(f"login: no challenge ({_describe_error(challenge)})")
        self._session = challenge.get("session") or 0

        login_params = dict(base)
        login_params.update(
            {
                "password": _rpc_password_hash(self._username, self._password, realm, random_),
                "realm": realm,
                "random": random_,
                "passwordType": "Default",
                "authorityType": params.get("encryption") or "Default",
            }
        )
        self._id += 1
        verdict = await self._exchange(
            {
                "method": "global.login",
                "params": login_params,
                "id": self._id,
                "session": self._session,
            },
            login=True,
        )
        if verdict.get("result") is not True:
            raise DahuaRpcError(f"login refused: {_describe_error(verdict)}")
        self._session = verdict.get("session") or self._session
        _LOGGER.debug("[RPC/%s] login OK", self.transport_name)

    async def logout(self) -> None:
        if not self._session:
            return
        try:
            await self.call("global.logout", None, check=False)
        except Exception:  # noqa: BLE001 - best effort
            pass
        self._session = 0

    async def ptz_object(self, channel0: int) -> int:
        resp = await self.call("ptz.factory.instance", {"channel": channel0})
        obj = resp.get("result")
        if isinstance(obj, bool) or not isinstance(obj, int) or obj <= 0:
            raise DahuaRpcError(f"ptz.factory.instance returned {obj!r}")
        return obj

    async def ptz_call(self, channel0: int, method: str, params: dict | None = None) -> dict:
        """Call a `ptz.*` method on this channel's PTZ object.

        Falls back to calling without an object (some firmware exposes
        `ptz.*` as plain static methods taking `channel`).
        """
        params = {"channel": channel0, **(params or {})}
        try:
            obj = await self.ptz_object(channel0)
        except DahuaRpcError as err:
            _LOGGER.debug("[RPC/%s] %s; trying %s without object", self.transport_name, err, method)
            return await self.call(method, params)
        return await self.call(method, params, obj)


class DahuaRpcHttp(_DahuaRpcBase):
    """RPC2 over the camera's HTTP port (`/RPC2_Login`, `/RPC2`)."""

    transport_name = "http"

    def __init__(self, session: aiohttp.ClientSession, base_url: str, username: str, password: str) -> None:
        super().__init__(username, password)
        self._http = session
        self._base = base_url.rstrip("/")

    async def _exchange(self, message: dict, login: bool = False) -> dict:
        url = f"{self._base}/RPC2_Login" if login else f"{self._base}/RPC2"
        try:
            async with self._http.post(
                url, json=message, timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as resp:
                if resp.status != 200:
                    raise DahuaRpcError(f"{message['method']}: HTTP {resp.status} from {url}")
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise DahuaRpcError(f"{message['method']}: {type(err).__name__}: {err}") from err
        try:
            data = json.loads(text.lstrip("﻿"))
        except ValueError as err:
            raise DahuaRpcError(f"{message['method']}: non-JSON reply from {url}") from err
        if not isinstance(data, dict):
            raise DahuaRpcError(f"{message['method']}: unexpected reply {data!r}")
        return data

    async def close(self) -> None:
        await self.logout()


class DahuaRpcDhip(_DahuaRpcBase):
    """RPC2 JSON envelopes framed in DHIP headers over TCP 37777.

    Header (32 bytes): `20 00 00 00` `"DHIP"`, session (u32 LE), request id
    (u32 LE), this packet's body length (u32 LE), 0, total body length
    (u32 LE), 0. Body is the JSON text (devices append `\\n`/NULs).
    """

    transport_name = "dhip"

    def __init__(self, host: str, username: str, password: str, port: int = DHIP_PORT) -> None:
        super().__init__(username, password)
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def _connect(self) -> None:
        if self._writer is not None:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=self._timeout
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise DahuaRpcError(f"connect {self._host}:{self._port}: {err}") from err

    def _frame(self, message: dict) -> bytes:
        body = json.dumps(message).encode()
        session = message.get("session") or 0
        try:
            session = int(session) & 0xFFFFFFFF
        except (TypeError, ValueError):
            session = 0
        header = _DHIP_MAGIC + struct.pack(
            "<IIIIII", session, int(message.get("id", 0)) & 0xFFFFFFFF, len(body), 0, len(body), 0
        )
        return header + body

    async def _read_message(self) -> dict:
        """Read one (possibly multi-packet) DHIP message and decode its JSON."""
        assert self._reader is not None
        body = b""
        total = None
        while total is None or len(body) < total:
            hdr = await self._reader.readexactly(_DHIP_HEADER_SIZE)
            if hdr[4:8] != b"DHIP":
                raise DahuaRpcError(f"not a DHIP reply (header {hdr[:8].hex()}) - port speaks another protocol")
            n = struct.unpack_from("<I", hdr, 16)[0]
            expect = struct.unpack_from("<I", hdr, 24)[0]
            if n > _DHIP_MAX_BODY or expect > _DHIP_MAX_BODY:
                raise DahuaRpcError(f"bogus DHIP length {n}/{expect}")
            body += await self._reader.readexactly(n) if n else b""
            total = expect or n
        text = body.rstrip(b"\x00\r\n ").decode(errors="replace")
        try:
            data = json.loads(text)
        except ValueError as err:
            raise DahuaRpcError(f"non-JSON DHIP body: {text[:120]!r}") from err
        if not isinstance(data, dict):
            raise DahuaRpcError(f"unexpected DHIP body {data!r}")
        return data

    async def _exchange(self, message: dict, login: bool = False) -> dict:
        await self._connect()
        assert self._writer is not None
        try:
            self._writer.write(self._frame(message))
            await self._writer.drain()
            # Skip unsolicited notifications until our id comes back.
            for _ in range(16):
                data = await asyncio.wait_for(self._read_message(), timeout=self._timeout)
                if data.get("id") == message.get("id"):
                    return data
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
            raise DahuaRpcError(f"{message['method']}: {type(err).__name__}: {err}") from err
        raise DahuaRpcError(f"{message['method']}: no matching DHIP reply")

    async def close(self) -> None:
        if self._writer is not None:
            await self.logout()
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = self._writer = None
