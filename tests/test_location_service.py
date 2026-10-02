"""SimulationService behaviour, driven by the fake backend (no device required)."""

import pytest

from loca_engine.backends.fake import FakeBackend
from loca_engine.domain.errors import EngineError, EngineErrorCode
from loca_engine.domain.geo import Direction, haversine_distance
from loca_engine.domain.models import SimulationStatus, StepCommand
from loca_engine.location.service import SimulationService

UDID = "00000000-FAKEDEVICE0000000001"


@pytest.fixture
def service() -> SimulationService:
    return SimulationService(FakeBackend())


async def test_diagnose_reports_ready(service: SimulationService):
    report = await service.diagnose(UDID)
    assert report.ready is True
    assert [c.id for c in report.checks][0] == "device_connected"


async def test_teleport_sets_active_state(service: SimulationService):
    state = await service.teleport(UDID, 35.681236, 139.767125)
    assert state.status is SimulationStatus.ACTIVE
    assert state.udid == UDID
    assert state.location is not None
    assert state.location.latitude == pytest.approx(35.681236)


async def test_step_moves_from_current_location(service: SimulationService):
    await service.teleport(UDID, 35.681236, 139.767125)
    before = service.state.location.coordinate
    state = await service.step(StepCommand(Direction.NORTH, 50.0))
    after = state.location.coordinate
    assert haversine_distance(before, after) == pytest.approx(50.0, abs=1e-2)
    # North move changes latitude only.
    assert after.longitude == pytest.approx(before.longitude, abs=1e-9)
    assert after.latitude > before.latitude


async def test_step_before_teleport_is_rejected(service: SimulationService):
    with pytest.raises(EngineError) as exc:
        await service.step(StepCommand(Direction.NORTH, 10.0))
    assert exc.value.code is EngineErrorCode.SIMULATION_FAILED


async def test_stop_returns_to_inactive(service: SimulationService):
    await service.teleport(UDID, 1.0, 2.0)
    state = await service.stop()
    assert state.status is SimulationStatus.INACTIVE
    assert state.location is None


async def test_stop_when_idle_is_safe(service: SimulationService):
    state = await service.stop()
    assert state.status is SimulationStatus.INACTIVE


async def test_teleport_unknown_device_raises(service: SimulationService):
    with pytest.raises(EngineError) as exc:
        await service.teleport("does-not-exist", 0.0, 0.0)
    assert exc.value.code is EngineErrorCode.DEVICE_NOT_FOUND


async def test_teleport_out_of_range_coordinate_rejected(service: SimulationService):
    with pytest.raises(ValueError):
        await service.teleport(UDID, 999.0, 0.0)


async def test_backend_records_sent_coordinates():
    backend = FakeBackend()
    service = SimulationService(backend)
    await service.teleport(UDID, 10.0, 20.0)
    await service.step(StepCommand(Direction.EAST, 25.0))
    assert len(backend.set_calls) == 2
    assert backend.set_calls[0] == (UDID, 10.0, 20.0)
    # moved east: longitude increased, latitude ~unchanged
    _, lat, lon = backend.set_calls[1]
    assert lon > 20.0
    assert lat == pytest.approx(10.0, abs=1e-6)


def test_fake_backend_set_before_start_rejected():
    import asyncio

    backend = FakeBackend()

    async def run():
        with pytest.raises(EngineError):
            await backend.set_location(UDID, 0.0, 0.0)  # no start_simulation first

    asyncio.run(run())
