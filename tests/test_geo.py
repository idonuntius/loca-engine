"""Tests for geodesic step movement (no device required — CI safe)."""

import math

import pytest

from loca_engine.domain.geo import (
    Coordinate,
    Direction,
    destination_point,
    haversine_distance,
    step,
)

TOKYO_STATION = Coordinate(latitude=35.681236, longitude=139.767125)


def test_coordinate_rejects_out_of_range():
    with pytest.raises(ValueError):
        Coordinate(latitude=91.0, longitude=0.0)
    with pytest.raises(ValueError):
        Coordinate(latitude=0.0, longitude=181.0)


@pytest.mark.parametrize("distance", [1.0, 5.0, 10.0, 50.0, 100.0])
@pytest.mark.parametrize("direction", list(Direction))
def test_step_moves_exact_distance(direction: Direction, distance: float):
    moved = step(TOKYO_STATION, direction, distance)
    measured = haversine_distance(TOKYO_STATION, moved)
    # Sub-millimeter agreement expected at these scales.
    assert measured == pytest.approx(distance, abs=1e-3)


def test_step_north_increases_latitude_only():
    moved = step(TOKYO_STATION, Direction.NORTH, 100.0)
    assert moved.latitude > TOKYO_STATION.latitude
    assert moved.longitude == pytest.approx(TOKYO_STATION.longitude, abs=1e-9)


def test_step_east_increases_longitude_only():
    moved = step(TOKYO_STATION, Direction.EAST, 100.0)
    assert moved.longitude > TOKYO_STATION.longitude
    assert moved.latitude == pytest.approx(TOKYO_STATION.latitude, abs=1e-6)


def test_north_then_south_returns_to_origin():
    north = step(TOKYO_STATION, Direction.NORTH, 50.0)
    back = step(north, Direction.SOUTH, 50.0)
    assert back.latitude == pytest.approx(TOKYO_STATION.latitude, abs=1e-9)
    assert back.longitude == pytest.approx(TOKYO_STATION.longitude, abs=1e-9)


def test_arbitrary_bearing_distance():
    moved = destination_point(TOKYO_STATION, 250.0, bearing_degrees=45.0)
    assert haversine_distance(TOKYO_STATION, moved) == pytest.approx(250.0, abs=1e-2)
    # NE bearing moves both lat and lon positive.
    assert moved.latitude > TOKYO_STATION.latitude
    assert moved.longitude > TOKYO_STATION.longitude


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        destination_point(TOKYO_STATION, -1.0, 0.0)


def test_haversine_known_distance():
    # ~1 degree of latitude ≈ 111.19 km on the mean sphere.
    a = Coordinate(0.0, 0.0)
    b = Coordinate(1.0, 0.0)
    assert haversine_distance(a, b) == pytest.approx(111_195, rel=1e-3)
    assert math.isclose(haversine_distance(a, a), 0.0)
