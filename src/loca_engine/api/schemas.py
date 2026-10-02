"""Pydantic request/response shapes and converters from domain models.

Kept separate from the domain dataclasses on purpose: the wire format can evolve
(field names, versioning) without touching core logic, and Swift decodes these stable
shapes rather than Python internals.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..domain.geo import Direction
from ..domain.models import (
    DeviceSummary,
    DiagnosticCheck,
    DiagnosticReport,
    SimulatedLocation,
    SimulationState,
)

_DIRECTIONS = {d.name.lower(): d for d in Direction}


def parse_direction(value: str) -> Direction:
    try:
        return _DIRECTIONS[value.strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"unknown direction {value!r}; expected one of {sorted(_DIRECTIONS)}"
        ) from exc


# ---- responses -------------------------------------------------------------


class ErrorOut(BaseModel):
    code: str
    message: str
    remedy: str | None = None


class DeviceOut(BaseModel):
    udid: str
    name: str
    product_type: str | None = None
    marketing_name: str | None = None
    ios_version: str | None = None
    build_version: str | None = None
    connection_type: str

    @classmethod
    def from_domain(cls, d: DeviceSummary) -> DeviceOut:
        return cls(
            udid=d.udid,
            name=d.name,
            product_type=d.product_type,
            marketing_name=d.marketing_name,
            ios_version=d.ios_version,
            build_version=d.build_version,
            connection_type=d.connection_type.value,
        )


class CheckOut(BaseModel):
    id: str
    title: str
    status: str
    detail: str | None = None
    remedy: str | None = None

    @classmethod
    def from_domain(cls, c: DiagnosticCheck) -> CheckOut:
        return cls(id=c.id, title=c.title, status=c.status.value, detail=c.detail, remedy=c.remedy)


class DoctorOut(BaseModel):
    udid: str
    ready: bool
    checks: list[CheckOut]

    @classmethod
    def from_domain(cls, r: DiagnosticReport) -> DoctorOut:
        return cls(udid=r.udid, ready=r.ready, checks=[CheckOut.from_domain(c) for c in r.checks])


class LocationOut(BaseModel):
    latitude: float
    longitude: float
    sent_at: datetime

    @classmethod
    def from_domain(cls, loc: SimulatedLocation) -> LocationOut:
        return cls(latitude=loc.latitude, longitude=loc.longitude, sent_at=loc.sent_at)


class StateOut(BaseModel):
    status: str
    udid: str | None = None
    location: LocationOut | None = None
    note: str | None = None

    @classmethod
    def from_domain(cls, s: SimulationState) -> StateOut:
        return cls(
            status=s.status.value,
            udid=s.udid,
            location=LocationOut.from_domain(s.location) if s.location else None,
            note=s.note,
        )


# ---- requests --------------------------------------------------------------


class TeleportIn(BaseModel):
    udid: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class StepIn(BaseModel):
    direction: str
    distance_meters: float = Field(gt=0)
