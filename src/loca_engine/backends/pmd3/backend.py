"""Pmd3Backend — the real :class:`LocationEngineBackend`.

Owns, for the currently simulated device, one native RSD tunnel and one held-open
LocationSimulation session. MVP scope is a single active session at a time (switching
devices stops the previous one); multi-device sessions are a later milestone.
"""

from __future__ import annotations

import asyncio
import logging

from ...domain.errors import EngineError, EngineErrorCode
from ...domain.models import DeviceSummary, DiagnosticCheck
from . import devices as devices_mod
from . import diagnostics as diagnostics_mod
from .session import LocationSession
from .tunnel import NativeTunnel

logger = logging.getLogger(__name__)


class Pmd3Backend:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_udid: str | None = None
        self._tunnel: NativeTunnel | None = None
        self._session: LocationSession | None = None

    async def list_devices(self) -> list[DeviceSummary]:
        return await devices_mod.list_devices()

    async def diagnose(self, udid: str) -> list[DiagnosticCheck]:
        # If this device already has a live session, the tunnel is in use — don't
        # open a second one just to probe; report what we know instead of lying.
        probe = not (self._active_udid == udid and self._session is not None)
        return await diagnostics_mod.diagnose(udid, probe_services=probe)

    async def start_simulation(self, udid: str) -> None:
        async with self._lock:
            if self._active_udid == udid and self._session is not None:
                return  # idempotent
            await self._teardown_locked()
            tunnel = NativeTunnel(udid)
            endpoint = await tunnel.start()
            session = LocationSession(endpoint)
            try:
                await session.start()
            except EngineError:
                await tunnel.stop()
                raise
            self._tunnel = tunnel
            self._session = session
            self._active_udid = udid
            logger.info("session started udid=%s rsd=%s:%s", udid, endpoint.host, endpoint.port)

    async def set_location(self, udid: str, latitude: float, longitude: float) -> None:
        async with self._lock:
            if self._active_udid != udid or self._session is None:
                raise EngineError(
                    EngineErrorCode.SIMULATION_FAILED,
                    "no active session for this device",
                    remedy="Start the simulation session before sending a location.",
                )
            await self._session.set(latitude, longitude)

    async def stop_simulation(self, udid: str) -> None:
        async with self._lock:
            if self._active_udid != udid:
                return  # nothing to stop for this device
            await self._teardown_locked()

    async def _teardown_locked(self) -> None:
        """Clear the location and release tunnel + session. Caller holds the lock."""
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception:  # noqa: BLE001 - best-effort clear
                logger.warning("error stopping location session", exc_info=True)
            self._session = None
        if self._tunnel is not None:
            await self._tunnel.stop()
            self._tunnel = None
        self._active_udid = None

    async def aclose(self) -> None:
        """Release everything (call on engine shutdown)."""
        async with self._lock:
            await self._teardown_locked()
