"""Pmd3Backend — the real :class:`LocationEngineBackend`.

Holds **one** native RSD tunnel per device and reuses it for everything (Connection
Doctor *and* location simulation). Creating/destroying native tunnels repeatedly
conflicts with Apple's single shared tunnel and hangs, so the tunnel is opened once
and kept until the device changes or the engine shuts down. The DVT LocationSimulation
session is layered on top of that tunnel and opened/closed as simulation starts/stops.

All device operations are serialized by one lock, so a long Doctor probe can't race a
teleport over the shared tunnel. Device listing and state reads don't take the lock, so
the API stays responsive while a device operation runs.
"""

from __future__ import annotations

import asyncio
import logging

from ...domain.errors import EngineError, EngineErrorCode
from ...domain.models import DeviceSummary, DiagnosticCheck, DiagnosticStatus
from . import devices as devices_mod
from . import diagnostics as diag
from .session import LocationSession
from .tunnel import NativeTunnel, RsdEndpoint

logger = logging.getLogger(__name__)


class Pmd3Backend:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_udid: str | None = None
        self._tunnel: NativeTunnel | None = None
        self._endpoint: RsdEndpoint | None = None
        self._session: LocationSession | None = None

    async def list_devices(self) -> list[DeviceSummary]:
        return await devices_mod.list_devices()

    async def diagnose(self, udid: str) -> list[DiagnosticCheck]:
        async with self._lock:
            checks = await diag.lockdown_checks(udid)
            # Only attempt the tunnel/DVT probe if the device is reachable and trusted.
            if (
                diag.status_of(checks, "device_connected") is not DiagnosticStatus.OK
                or diag.status_of(checks, "trusted") is not DiagnosticStatus.OK
            ):
                checks.extend(diag.tunnel_unavailable_checks("device not connected or trusted"))
                return checks

            try:
                endpoint = await self._ensure_tunnel_locked(udid)
            except EngineError as exc:
                checks.extend(diag.tunnel_unavailable_checks(exc.message))
                return checks

            # A live simulation session already proves both services; don't open a second
            # DVT channel on the same tunnel.
            if self._session is not None:
                checks.extend(diag.services_ok_checks())
            else:
                checks.extend(await diag.probe_dvt(endpoint))
            return checks

    async def start_simulation(self, udid: str) -> None:
        async with self._lock:
            endpoint = await self._ensure_tunnel_locked(udid)
            if self._session is not None:
                return  # idempotent
            session = LocationSession(endpoint)
            await session.start()
            self._session = session
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
            if self._active_udid != udid or self._session is None:
                return
            await self._close_session_locked()

    async def aclose(self) -> None:
        async with self._lock:
            await self._teardown_locked()

    # --- internal (caller holds the lock) ----------------------------------

    async def _ensure_tunnel_locked(self, udid: str) -> RsdEndpoint:
        """Return a live tunnel endpoint for ``udid``, reusing the existing one."""
        if self._tunnel is not None and self._tunnel.alive and self._active_udid == udid:
            assert self._endpoint is not None
            return self._endpoint
        # Different device or dead tunnel: tear everything down and start fresh.
        await self._teardown_locked()
        tunnel = NativeTunnel(udid)
        endpoint = await tunnel.start()
        self._tunnel = tunnel
        self._endpoint = endpoint
        self._active_udid = udid
        return endpoint

    async def _close_session_locked(self) -> None:
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception:  # noqa: BLE001 - best-effort clear
                logger.warning("error stopping location session", exc_info=True)
            self._session = None

    async def _teardown_locked(self) -> None:
        await self._close_session_locked()
        if self._tunnel is not None:
            await self._tunnel.stop()
            self._tunnel = None
        self._endpoint = None
        self._active_udid = None
