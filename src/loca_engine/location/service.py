"""SimulationService — the engine's single source of truth.

Everything that mutates "what location is being sent, to which device" goes through
one instance of this class. It owns the :class:`SimulationState`, serializes changes
with a lock, and composes the (device-agnostic) backend with the pure geodesy in
:mod:`loca_engine.domain.geo`.

It deliberately does *not* read the simulated location back from the device: the DVT
LocationSimulation channel is write-only, so the last value we sent is the only honest
source. Movement (step / future joystick) is computed from that stored value.
"""

from __future__ import annotations

import asyncio
import logging

from ..backends.base import LocationEngineBackend
from ..domain import geo
from ..domain.errors import EngineError, EngineErrorCode
from ..domain.models import (
    DeviceSummary,
    DiagnosticCheck,
    DiagnosticReport,
    SimulatedLocation,
    SimulationState,
    SimulationStatus,
    StepCommand,
)

logger = logging.getLogger(__name__)


class SimulationService:
    def __init__(self, backend: LocationEngineBackend) -> None:
        self._backend = backend
        self._state = SimulationState()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> SimulationState:
        return self._state

    async def list_devices(self) -> list[DeviceSummary]:
        return await self._backend.list_devices()

    async def diagnose(self, udid: str) -> DiagnosticReport:
        checks: list[DiagnosticCheck] = await self._backend.diagnose(udid)
        return DiagnosticReport(udid=udid, checks=tuple(checks))

    async def teleport(self, udid: str, latitude: float, longitude: float) -> SimulationState:
        """Set the device to an absolute coordinate, starting a session if needed."""
        location = SimulatedLocation(latitude=latitude, longitude=longitude)  # validates range
        async with self._lock:
            await self._switch_device_if_needed(udid)
            await self._backend.start_simulation(udid)
            await self._backend.set_location(udid, location.latitude, location.longitude)
            self._state = SimulationState(
                status=SimulationStatus.ACTIVE, udid=udid, location=location
            )
            logger.info("teleport udid=%s lat=%s lon=%s", udid, latitude, longitude)
            return self._state

    async def move(self, bearing_degrees: float, distance_meters: float) -> SimulationState:
        """Move ``distance_meters`` from the current location along ``bearing_degrees``.

        Bearing is a true compass heading (0 = North, 90 = East); any angle is allowed,
        so continuous joystick movement can follow a road at any orientation.
        """
        async with self._lock:
            current = self._state.location
            if self._state.status is not SimulationStatus.ACTIVE or current is None:
                raise EngineError(
                    EngineErrorCode.SIMULATION_FAILED,
                    "no active simulated location to move from",
                    remedy="Teleport to a starting point before moving.",
                )
            udid = self._state.udid
            assert udid is not None
            destination = geo.destination_point(
                current.coordinate, distance_meters, bearing_degrees
            )
            moved = SimulatedLocation.at(destination)
            await self._backend.set_location(udid, moved.latitude, moved.longitude)
            self._state = SimulationState(status=SimulationStatus.ACTIVE, udid=udid, location=moved)
            logger.info(
                "move udid=%s bearing=%.1f dist=%sm -> lat=%s lon=%s",
                udid,
                bearing_degrees,
                distance_meters,
                moved.latitude,
                moved.longitude,
            )
            return self._state

    async def step(self, command: StepCommand) -> SimulationState:
        """Move a fixed distance in a cardinal direction (N/S/E/W)."""
        return await self.move(command.direction.bearing_degrees, command.distance_meters)

    async def stop(self) -> SimulationState:
        """Stop simulation and restore the real GPS, best-effort.

        If the device's real location cannot be confirmed as restored, the state
        becomes UNKNOWN (never silently INACTIVE) so the UI can warn the user.
        """
        async with self._lock:
            udid = self._state.udid
            if udid is None or self._state.status is SimulationStatus.INACTIVE:
                self._state = SimulationState(status=SimulationStatus.INACTIVE)
                return self._state
            try:
                await self._backend.stop_simulation(udid)
                self._state = SimulationState(status=SimulationStatus.INACTIVE)
                logger.info("stop udid=%s -> inactive", udid)
            except EngineError as exc:
                self._state = SimulationState(
                    status=SimulationStatus.UNKNOWN,
                    udid=udid,
                    location=self._state.location,
                    note=f"could not confirm real location was restored: {exc.message}",
                )
                logger.warning("stop udid=%s failed: %s", udid, exc.message)
            return self._state

    async def _switch_device_if_needed(self, udid: str) -> None:
        """If a different device currently has an active session, stop it first."""
        active = self._state.udid
        if active is not None and active != udid and self._state.status is SimulationStatus.ACTIVE:
            try:
                await self._backend.stop_simulation(active)
            except EngineError:
                logger.warning("failed to stop previous device %s while switching", active)
