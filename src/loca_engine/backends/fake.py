"""In-memory fake backend.

Implements :class:`LocationEngineBackend` without any device, so the service, API and
CLI can be exercised in tests and so the macOS app can be built against a mock while
no iPhone is attached. It also mirrors the real backend's *rules* (must start a
session before setting a location) so tests catch ordering bugs.
"""

from __future__ import annotations

from ..domain.errors import EngineError, EngineErrorCode
from ..domain.models import (
    ConnectionType,
    DeviceSummary,
    DiagnosticCheck,
    DiagnosticStatus,
)


def _default_devices() -> list[DeviceSummary]:
    return [
        DeviceSummary(
            udid="00000000-FAKEDEVICE0000000001",
            name="Fake iPhone",
            product_type="iPhone16,1",
            marketing_name="iPhone 15 Pro",
            ios_version="26.5.2",
            build_version="23F84",
            connection_type=ConnectionType.USB,
        )
    ]


def _all_ok_checks() -> list[DiagnosticCheck]:
    titles = [
        ("device_connected", "Device connected"),
        ("trusted", "Trusted"),
        ("developer_mode", "Developer Mode enabled"),
        ("ddi_mounted", "Developer Disk Image ready"),
        ("rsd_tunnel", "RSD tunnel available"),
        ("location_simulation", "Location Simulation available"),
    ]
    return [DiagnosticCheck(id=i, title=t, status=DiagnosticStatus.OK) for i, t in titles]


class FakeBackend:
    """A controllable, deterministic backend for tests and UI development."""

    def __init__(
        self,
        devices: list[DeviceSummary] | None = None,
        checks: list[DiagnosticCheck] | None = None,
    ) -> None:
        self._devices = devices if devices is not None else _default_devices()
        self._checks = checks if checks is not None else _all_ok_checks()
        self._active_sessions: set[str] = set()
        # Recorded history so tests can assert what was sent.
        self.set_calls: list[tuple[str, float, float]] = []

    def _require_known_device(self, udid: str) -> None:
        if not any(d.udid == udid for d in self._devices):
            raise EngineError(
                EngineErrorCode.DEVICE_NOT_FOUND,
                f"no device with udid {udid}",
                remedy="Reconnect the iPhone and make sure it is unlocked and trusted.",
            )

    async def list_devices(self) -> list[DeviceSummary]:
        return list(self._devices)

    async def diagnose(self, udid: str) -> list[DiagnosticCheck]:
        self._require_known_device(udid)
        return list(self._checks)

    async def start_simulation(self, udid: str) -> None:
        self._require_known_device(udid)
        self._active_sessions.add(udid)

    async def set_location(self, udid: str, latitude: float, longitude: float) -> None:
        self._require_known_device(udid)
        if udid not in self._active_sessions:
            raise EngineError(
                EngineErrorCode.SIMULATION_FAILED,
                "set_location called before start_simulation",
                remedy="Start the simulation session before sending a location.",
            )
        self.set_calls.append((udid, latitude, longitude))

    async def stop_simulation(self, udid: str) -> None:
        # Best-effort and idempotent, exactly like the real backend.
        self._active_sessions.discard(udid)

    @property
    def is_active(self) -> bool:
        return bool(self._active_sessions)
