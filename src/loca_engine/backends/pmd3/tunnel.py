"""Native RSD tunnel management.

On macOS, ``pymobiledevice3 remote start-tunnel --native`` piggybacks Apple's own
device tunnel and needs **no root** (confirmed in the Phase 1 PoC). It prints an
``RSD Address`` / ``RSD Port`` and must stay alive for the tunnel to remain usable, so
we run it as a child process and keep the handle for the session's lifetime.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass

from ...domain.errors import EngineError, EngineErrorCode

_RSD_ADDR = re.compile(r"RSD Address:\s*(\S+)")
_RSD_PORT = re.compile(r"RSD Port:\s*(\d+)")
_TUNNEL_TIMEOUT_S = 20.0


@dataclass(frozen=True, slots=True)
class RsdEndpoint:
    host: str
    port: int


class NativeTunnel:
    """A root-free macOS native RSD tunnel held open as a child process."""

    def __init__(self, udid: str | None = None) -> None:
        self._udid = udid
        self._proc: asyncio.subprocess.Process | None = None
        self.endpoint: RsdEndpoint | None = None

    async def start(self) -> RsdEndpoint:
        if getattr(sys, "frozen", False):
            # Frozen build: `sys.executable` is the loca-engine binary, which can't run
            # `-m pymobiledevice3`. Re-invoke our multi-call `pmd3` entry (see cli.main),
            # which dispatches into the bundled pymobiledevice3 CLI.
            cmd = [sys.executable, "pmd3", "remote", "start-tunnel", "--native"]
        else:
            cmd = [sys.executable, "-m", "pymobiledevice3", "remote", "start-tunnel", "--native"]
        if self._udid:
            cmd += ["--udid", self._udid]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            self.endpoint = await asyncio.wait_for(self._read_endpoint(), _TUNNEL_TIMEOUT_S)
        except TimeoutError:
            await self.stop()
            raise EngineError(
                EngineErrorCode.RSD_TUNNEL_UNAVAILABLE,
                "timed out establishing the RSD tunnel",
                remedy="Unlock and trust the iPhone, enable Developer Mode, then retry.",
            ) from None
        return self.endpoint

    async def _read_endpoint(self) -> RsdEndpoint:
        assert self._proc is not None and self._proc.stdout is not None
        host = ""
        port = 0
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                raise EngineError(
                    EngineErrorCode.RSD_TUNNEL_UNAVAILABLE,
                    "tunnel process exited before reporting an RSD endpoint",
                    remedy="Unlock and trust the iPhone, enable Developer Mode, then retry.",
                )
            line = raw.decode(errors="replace")
            if (m := _RSD_ADDR.search(line)) and not host:
                host = m.group(1)
            if (m := _RSD_PORT.search(line)) and not port:
                port = int(m.group(1))
            if host and port:
                return RsdEndpoint(host=host, port=port)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()
