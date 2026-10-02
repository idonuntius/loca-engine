"""The backend boundary.

This Protocol is the Python mirror of the Swift ``LocationEngineClient``: the set of
operations the rest of the system needs, expressed without any reference to how they
are implemented. Backends raise :class:`loca_engine.domain.errors.EngineError` (never
raw library exceptions) so callers react to typed error *codes*, not message text.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DeviceSummary, DiagnosticCheck


@runtime_checkable
class LocationEngineBackend(Protocol):
    """Everything the engine needs from a device backend."""

    async def list_devices(self) -> list[DeviceSummary]:
        """Return all currently reachable devices (USB today, Wi-Fi later)."""
        ...

    async def diagnose(self, udid: str) -> list[DiagnosticCheck]:
        """Run the Connection Doctor checks for a device, in display order."""
        ...

    async def start_simulation(self, udid: str) -> None:
        """Open and hold a location-simulation session for the device.

        Must be called before :meth:`set_location`. Idempotent: starting an already
        started session is a no-op.
        """
        ...

    async def set_location(self, udid: str, latitude: float, longitude: float) -> None:
        """Send a simulated latitude/longitude. Requires an active session."""
        ...

    async def stop_simulation(self, udid: str) -> None:
        """Clear the simulated location and tear the session down.

        Must make a best effort to restore the device's real GPS even if the session
        is in a bad state. Idempotent.
        """
        ...
