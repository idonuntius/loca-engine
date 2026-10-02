"""API tests using the fake backend via FastAPI's TestClient (no device required)."""

import pytest
from fastapi.testclient import TestClient

from loca_engine.api import create_app
from loca_engine.backends.fake import FakeBackend
from loca_engine.location.service import SimulationService

UDID = "00000000-FAKEDEVICE0000000001"


@pytest.fixture
def client() -> TestClient:
    service = SimulationService(FakeBackend())
    return TestClient(create_app(service))


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_devices(client: TestClient):
    r = client.get("/devices")
    assert r.status_code == 200
    devices = r.json()
    assert devices[0]["udid"] == UDID
    assert devices[0]["connection_type"] == "usb"


def test_doctor_ready(client: TestClient):
    r = client.get(f"/devices/{UDID}/doctor")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert len(body["checks"]) == 6


def test_teleport_step_stop_flow(client: TestClient):
    r = client.post(
        "/simulation/teleport",
        json={"udid": UDID, "latitude": 35.681236, "longitude": 139.767125},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    r = client.post("/simulation/step", json={"direction": "north", "distance_meters": 10})
    assert r.status_code == 200
    assert r.json()["location"]["latitude"] > 35.681236

    r = client.post("/simulation/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"


def test_teleport_unknown_device_returns_404(client: TestClient):
    r = client.post(
        "/simulation/teleport",
        json={"udid": "nope", "latitude": 0.0, "longitude": 0.0},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "device_not_found"
    assert r.json()["remedy"]


def test_teleport_out_of_range_returns_422(client: TestClient):
    r = client.post(
        "/simulation/teleport",
        json={"udid": UDID, "latitude": 100.0, "longitude": 0.0},
    )
    assert r.status_code == 422  # pydantic validation


def test_step_before_teleport_returns_409(client: TestClient):
    r = client.post("/simulation/step", json={"direction": "north", "distance_meters": 10})
    assert r.status_code == 409
    assert r.json()["code"] == "simulation_failed"


def test_websocket_movement(client: TestClient):
    client.post(
        "/simulation/teleport",
        json={"udid": UDID, "latitude": 0.0, "longitude": 0.0},
    )
    with client.websocket_connect("/ws/movement") as ws:
        ws.send_json({"direction": "east", "distance_meters": 5})
        reply = ws.receive_json()
        assert reply["ok"] is True
        assert reply["state"]["location"]["longitude"] > 0.0


def test_websocket_bad_direction(client: TestClient):
    client.post(
        "/simulation/teleport",
        json={"udid": UDID, "latitude": 0.0, "longitude": 0.0},
    )
    with client.websocket_connect("/ws/movement") as ws:
        ws.send_json({"direction": "upward", "distance_meters": 5})
        reply = ws.receive_json()
        assert reply["ok"] is False
