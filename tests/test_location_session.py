"""LocationSession keep-alive, with the pymobiledevice3 channel faked out (no device required)."""

import asyncio

import pytest

from loca_engine.backends.pmd3 import session as session_mod
from loca_engine.backends.pmd3.session import LocationSession
from loca_engine.backends.pmd3.tunnel import RsdEndpoint

INTERVAL = 0.05


class _FakeContext:
    def __init__(self, *_args) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> None:
        return None


class _FakeSimulation(_FakeContext):
    instances: list["_FakeSimulation"] = []

    def __init__(self, *_args) -> None:
        self.sent: list[tuple[float, float]] = []
        self.cleared = False
        self.fail = False
        _FakeSimulation.instances.append(self)

    async def set(self, latitude: float, longitude: float) -> None:
        if self.fail:
            raise OSError("channel closed")
        self.sent.append((latitude, longitude))

    async def clear(self) -> None:
        self.cleared = True


@pytest.fixture
async def started(monkeypatch: pytest.MonkeyPatch):
    _FakeSimulation.instances.clear()
    monkeypatch.setattr(session_mod, "RemoteServiceDiscoveryService", _FakeContext)
    monkeypatch.setattr(session_mod, "DvtProvider", _FakeContext)
    monkeypatch.setattr(session_mod, "LocationSimulation", _FakeSimulation)
    session = LocationSession(RsdEndpoint("::1", 1), keepalive_interval=INTERVAL)
    await session.start()
    yield session, _FakeSimulation.instances[0]
    await session.stop()


async def test_idle_session_sends_nothing_before_first_set(started):
    _session, sim = started
    await asyncio.sleep(INTERVAL * 4)
    assert sim.sent == []


async def test_held_location_is_resent_while_idle(started):
    session, sim = started
    await session.set(35.0, 139.0)
    await asyncio.sleep(INTERVAL * 5)
    assert len(sim.sent) >= 3
    assert set(sim.sent) == {(35.0, 139.0)}


async def test_keepalive_follows_the_latest_location(started):
    session, sim = started
    await session.set(35.0, 139.0)
    await session.set(36.0, 140.0)
    await asyncio.sleep(INTERVAL * 3)
    assert sim.sent[-1] == (36.0, 140.0)
    assert (35.0, 139.0) not in sim.sent[2:]


async def test_keepalive_stops_after_a_failure_and_rearms_on_set(started):
    session, sim = started
    await session.set(35.0, 139.0)
    sim.fail = True
    await asyncio.sleep(INTERVAL * 3)
    sim.fail = False
    count = len(sim.sent)
    await asyncio.sleep(INTERVAL * 3)
    assert len(sim.sent) == count  # disarmed after the failed re-send
    await session.set(36.0, 140.0)
    await asyncio.sleep(INTERVAL * 3)
    assert sim.sent.count((36.0, 140.0)) >= 2


async def test_stop_clears_and_ends_keepalive(started):
    session, sim = started
    await session.set(35.0, 139.0)
    await session.stop()
    assert sim.cleared is True
    count = len(sim.sent)
    await asyncio.sleep(INTERVAL * 3)
    assert len(sim.sent) == count
