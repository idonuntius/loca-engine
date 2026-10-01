"""Geodesic helpers for step / continuous movement.

Step movement must move a point by a true on-the-ground distance (meters), not by
naive addition to latitude/longitude. We use the spherical-earth *destination point*
formula (a.k.a. direct geodesic on a sphere), which is accurate to well under a meter
for the short distances (1m–100m) this tool deals with.

Reference: http://www.movable-type.co.uk/scripts/latlong.html
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# Mean Earth radius (IUGG), meters. Good enough for sub-100m moves.
EARTH_RADIUS_M = 6_371_008.8


class Direction(Enum):
    """Cardinal directions, expressed as a compass bearing in degrees."""

    NORTH = 0.0
    EAST = 90.0
    SOUTH = 180.0
    WEST = 270.0

    @property
    def bearing_degrees(self) -> float:
        return float(self.value)


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS84 latitude/longitude pair in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range [-90, 90]: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range [-180, 180]: {self.longitude}")


def destination_point(
    origin: Coordinate,
    distance_meters: float,
    bearing_degrees: float,
) -> Coordinate:
    """Return the coordinate reached by travelling ``distance_meters`` from ``origin``
    along the given compass ``bearing_degrees`` (0 = North, 90 = East).

    Uses the spherical destination-point formula.
    """
    if distance_meters < 0:
        raise ValueError(f"distance_meters must be non-negative: {distance_meters}")

    angular_distance = distance_meters / EARTH_RADIUS_M
    bearing = math.radians(bearing_degrees)

    lat1 = math.radians(origin.latitude)
    lon1 = math.radians(origin.longitude)

    sin_lat2 = math.sin(lat1) * math.cos(angular_distance) + math.cos(lat1) * math.sin(
        angular_distance
    ) * math.cos(bearing)
    lat2 = math.asin(sin_lat2)

    y = math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1)
    x = math.cos(angular_distance) - math.sin(lat1) * sin_lat2
    lon2 = lon1 + math.atan2(y, x)

    # Normalize longitude back into [-180, 180].
    lon2_deg = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return Coordinate(latitude=math.degrees(lat2), longitude=lon2_deg)


def step(origin: Coordinate, direction: Direction, distance_meters: float) -> Coordinate:
    """Move ``distance_meters`` from ``origin`` toward a cardinal ``direction``."""
    return destination_point(origin, distance_meters, direction.bearing_degrees)


def haversine_distance(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance between two coordinates, in meters."""
    lat1 = math.radians(a.latitude)
    lat2 = math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)

    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))
