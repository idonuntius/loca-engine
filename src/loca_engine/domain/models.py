"""Shared, transport-agnostic data models.

These are the DTOs exchanged across every boundary (backend ⇄ service ⇄ API ⇄
Swift/CLI). They are intentionally plain and serializable, and they never reference
pymobiledevice3 types — the whole point is that the rest of the system is unaware of
how location injection is actually performed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .geo import Coordinate, Direction


class ConnectionType(StrEnum):
    USB = "usb"
    WIFI = "wifi"  # reserved for future Wi-Fi device support
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeviceSummary:
    """Minimal, display-ready description of a connected device."""

    udid: str
    name: str
    product_type: str | None = None  # e.g. "iPhone16,1"
    marketing_name: str | None = None  # e.g. "iPhone 15 Pro"
    ios_version: str | None = None  # e.g. "26.5.2"
    build_version: str | None = None
    connection_type: ConnectionType = ConnectionType.UNKNOWN


class DiagnosticStatus(StrEnum):
    OK = "ok"
    FAIL = "fail"
    WARN = "warn"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One line of the Connection Doctor, with an actionable remedy on failure."""

    id: str  # stable machine id, e.g. "developer_mode"
    title: str  # human label, e.g. "Developer Mode enabled"
    status: DiagnosticStatus
    detail: str | None = None  # short, non-raw explanation
    remedy: str | None = None  # what the user should do next, if not OK


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    udid: str
    checks: tuple[DiagnosticCheck, ...]

    @property
    def ready(self) -> bool:
        """True only if every check passed (no FAIL / UNKNOWN)."""
        return all(c.status is DiagnosticStatus.OK for c in self.checks)


@dataclass(frozen=True, slots=True)
class SimulatedLocation:
    """A location we actually send to the device.

    Only latitude/longitude are injectable via the current backend. Altitude / speed
    / course are deliberately *not* modeled here: the PoC confirmed they cannot be
    sent, and we must never display guessed values.
    """

    latitude: float
    longitude: float
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        # Validate via Coordinate so out-of-range values are rejected at the model
        # boundary, not only by the API's request schema.
        Coordinate(self.latitude, self.longitude)

    @property
    def coordinate(self) -> Coordinate:
        return Coordinate(self.latitude, self.longitude)

    @classmethod
    def at(cls, coordinate: Coordinate) -> SimulatedLocation:
        return cls(latitude=coordinate.latitude, longitude=coordinate.longitude)


@dataclass(frozen=True, slots=True)
class StepCommand:
    """Move a fixed distance in a cardinal direction from the current location."""

    direction: Direction
    distance_meters: float


class SimulationStatus(StrEnum):
    """Lifecycle of the simulation for a device.

    UNKNOWN is a first-class state: when we cannot confirm the device returned to its
    real GPS (e.g. the engine crashed while a location was active), we must say so
    rather than imply everything is fine.
    """

    INACTIVE = "inactive"  # no simulated location is being sent
    ACTIVE = "active"  # a simulated location is currently held on the device
    UNKNOWN = "unknown"  # we cannot confirm the real location was restored


@dataclass(frozen=True, slots=True)
class SimulationState:
    """Single source of truth for 'what are we currently sending, to which device'."""

    status: SimulationStatus = SimulationStatus.INACTIVE
    udid: str | None = None
    location: SimulatedLocation | None = None
    note: str | None = None  # e.g. reason the status is UNKNOWN
