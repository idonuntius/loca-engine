"""A held-open DVT LocationSimulation session.

The DVT LocationSimulation channel is *write-only* and clears the simulated location
the moment it closes. To keep a teleported location in place (and to re-send new
coordinates quickly for step / joystick movement), the channel must stay open.

We keep it open inside a single dedicated asyncio task (an "actor") that owns the
``async with`` scope. Callers submit commands over a queue; the actor guarantees the
channel is torn down correctly (via ``__aexit__``) even on cancellation or error. This
avoids juggling ``__aenter__``/``__aexit__`` by hand across many request handlers.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

from ...domain.errors import EngineError, EngineErrorCode
from .tunnel import RsdEndpoint

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SetCommand:
    latitude: float
    longitude: float
    future: asyncio.Future[None]


class LocationSession:
    """Owns an open LocationSimulation channel for one device."""

    def __init__(self, endpoint: RsdEndpoint) -> None:
        self._endpoint = endpoint
        self._queue: asyncio.Queue[_SetCommand | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run(), name="loca-location-session")
        await self._ready  # raises if the channel could not be opened

    async def set(self, latitude: float, longitude: float) -> None:
        if self._task is None or self._task.done():
            raise EngineError(
                EngineErrorCode.SIMULATION_FAILED,
                "location session is not running",
                remedy="Start the simulation session before sending a location.",
            )
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        await self._queue.put(_SetCommand(latitude, longitude, fut))
        await fut

    async def stop(self) -> None:
        """Clear the location and close the channel. Best-effort and idempotent."""
        if self._task is None or self._task.done():
            return
        await self._queue.put(None)  # sentinel: clear + exit the actor
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=10)
        except TimeoutError:
            self._task.cancel()

    async def _run(self) -> None:
        assert self._ready is not None
        try:
            rsd = RemoteServiceDiscoveryService((self._endpoint.host, self._endpoint.port))
            async with rsd, DvtProvider(rsd) as dvt, LocationSimulation(dvt) as sim:
                if not self._ready.done():
                    self._ready.set_result(None)
                await self._serve(sim)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - translate any library failure
            logger.exception("location session failed")
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(
                    EngineError(
                        EngineErrorCode.LOCATION_SIMULATION_UNAVAILABLE,
                        f"could not open location simulation channel: {exc}",
                        remedy="Re-run Connection Doctor; ensure Developer Mode and the "
                        "Developer Disk Image are ready.",
                    )
                )

    async def _serve(self, sim: LocationSimulation) -> None:
        while True:
            command = await self._queue.get()
            if command is None:  # stop sentinel
                try:
                    await sim.clear()
                except Exception:  # noqa: BLE001 - best-effort clear on shutdown
                    logger.warning("failed to clear location on stop", exc_info=True)
                return
            try:
                await sim.set(command.latitude, command.longitude)
                command.future.set_result(None)
            except Exception as exc:  # noqa: BLE001
                if not command.future.done():
                    command.future.set_exception(
                        EngineError(
                            EngineErrorCode.SIMULATION_FAILED,
                            f"failed to set location: {exc}",
                        )
                    )
