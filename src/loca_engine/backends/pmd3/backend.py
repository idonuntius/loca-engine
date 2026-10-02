"""Pmd3Backend — the real :class:`LocationEngineBackend`.

Holds **one** native RSD tunnel per device and reuses it for everything (Connection
Doctor *and* location simulation). Creating/destroying native tunnels repeatedly
conflicts with Apple's single shared tunnel and hangs, so the tunnel is opened once and
reused.

A reused tunnel can still go stale (e.g. the iPhone locks, or Apple's tunnel resets),
in which case connecting to its RSD endpoint would otherwise hang. Every tunnel-using
operation is therefore bounded by a timeout and retried once on a freshly started
tunnel; if that still fails we raise a typed error with a remedy instead of freezing.

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

LOCKDOWN_TIMEOUT = 10.0


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
            try:
                checks = await asyncio.wait_for(
                    diag.lockdown_checks(udid), timeout=LOCKDOWN_TIMEOUT
                )
            except TimeoutError:
                checks = diag.unresponsive_checks()
                checks.extend(diag.tunnel_unavailable_checks("device not responding"))
                return checks
            if (
                diag.status_of(checks, "device_connected") is not DiagnosticStatus.OK
                or diag.status_of(checks, "trusted") is not DiagnosticStatus.OK
            ):
                checks.extend(diag.tunnel_unavailable_checks("device not connected or trusted"))
                return checks
            checks.extend(await self._tunnel_checks_locked(udid))
            return checks

    async def start_simulation(self, udid: str) -> None:
        async with self._lock:
            if self._session is not None and self._active_udid == udid:
                return  # idempotent
            await self._start_session_locked(udid)

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

    async def _start_session_locked(self, udid: str) -> None:
        """Open a DVT session, reusing the tunnel then retrying on a fresh one."""
        last_error: EngineError | None = None
        for force_fresh in (False, True):
            endpoint = await self._ensure_tunnel_locked(udid, force_fresh=force_fresh)
            session = LocationSession(endpoint)
            try:
                await session.start()
                self._session = session
                logger.info("session started udid=%s rsd=%s:%s", udid, endpoint.host, endpoint.port)
                return
            except EngineError as exc:
                last_error = exc
                logger.warning("session start failed (fresh=%s): %s", force_fresh, exc.message)
                await self._teardown_tunnel_locked()  # drop the stale tunnel before retrying
        raise last_error or EngineError(
            EngineErrorCode.SIMULATION_FAILED, "could not start the simulation session"
        )

    async def _tunnel_checks_locked(self, udid: str) -> list[DiagnosticCheck]:
        """Doctor checks 5–6: make sure a tunnel is available (reuse, else start one).

        Does not open a DVT channel — see :func:`diagnostics.services_ok_checks`. If a
        live session exists the tunnel is already proven good.
        """
        if self._session is not None and self._active_udid == udid:
            return diag.services_ok_checks()
        try:
            await self._ensure_tunnel_locked(udid, force_fresh=False)
        except EngineError:
            try:
                await self._ensure_tunnel_locked(udid, force_fresh=True)
            except EngineError as exc:
                return diag.tunnel_unavailable_checks(exc.message)
        return diag.services_ok_checks()

    async def _ensure_tunnel_locked(self, udid: str, *, force_fresh: bool) -> RsdEndpoint:
        if (
            not force_fresh
            and self._tunnel is not None
            and self._tunnel.alive
            and self._active_udid == udid
        ):
            assert self._endpoint is not None
            return self._endpoint
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

    async def _teardown_tunnel_locked(self) -> None:
        if self._tunnel is not None:
            await self._tunnel.stop()
            self._tunnel = None
        self._endpoint = None
        self._active_udid = None

    async def _teardown_locked(self) -> None:
        await self._close_session_locked()
        await self._teardown_tunnel_locked()
