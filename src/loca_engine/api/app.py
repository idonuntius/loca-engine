"""FastAPI application factory.

``create_app(service)`` wires routes to a :class:`SimulationService`, so the same app
can run against the real pymobiledevice3 backend or a fake one in tests. Every
:class:`EngineError` is turned into a stable JSON error shape; raw exceptions never
reach the client.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ..domain.errors import EngineError, EngineErrorCode
from ..domain.models import StepCommand
from ..location.service import SimulationService
from .schemas import (
    DeviceOut,
    DoctorOut,
    ErrorOut,
    StateOut,
    StepIn,
    TeleportIn,
    parse_direction,
)

logger = logging.getLogger(__name__)

_STATUS_FOR_CODE = {
    EngineErrorCode.DEVICE_NOT_FOUND: 404,
    EngineErrorCode.DEVICE_NOT_TRUSTED: 409,
    EngineErrorCode.DEVICE_LOCKED: 409,
    EngineErrorCode.DEVELOPER_MODE_DISABLED: 409,
    EngineErrorCode.DDI_NOT_MOUNTED: 409,
    EngineErrorCode.RSD_TUNNEL_UNAVAILABLE: 409,
    EngineErrorCode.PERMISSION_REQUIRED: 403,
    EngineErrorCode.LOCATION_SIMULATION_UNAVAILABLE: 409,
    EngineErrorCode.SIMULATION_FAILED: 409,
    EngineErrorCode.BACKEND_UNAVAILABLE: 503,
}


def create_app(
    service: SimulationService,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    app = FastAPI(title="loca-engine", version="0.0.1", lifespan=lifespan)

    @app.exception_handler(EngineError)
    async def _engine_error_handler(_request, exc: EngineError) -> JSONResponse:
        status = _STATUS_FOR_CODE.get(exc.code, 409)
        body = ErrorOut(code=exc.code.value, message=exc.message, remedy=exc.remedy)
        return JSONResponse(status_code=status, content=body.model_dump())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/devices", response_model=list[DeviceOut])
    async def list_devices() -> list[DeviceOut]:
        return [DeviceOut.from_domain(d) for d in await service.list_devices()]

    @app.get("/devices/{udid}/doctor", response_model=DoctorOut)
    async def doctor(udid: str) -> DoctorOut:
        return DoctorOut.from_domain(await service.diagnose(udid))

    @app.get("/simulation", response_model=StateOut)
    async def get_state() -> StateOut:
        return StateOut.from_domain(service.state)

    @app.post("/simulation/teleport", response_model=StateOut)
    async def teleport(body: TeleportIn) -> StateOut:
        state = await service.teleport(body.udid, body.latitude, body.longitude)
        return StateOut.from_domain(state)

    @app.post("/simulation/step", response_model=StateOut)
    async def step(body: StepIn) -> StateOut:
        command = StepCommand(parse_direction(body.direction), body.distance_meters)
        return StateOut.from_domain(await service.step(command))

    @app.post("/simulation/stop", response_model=StateOut)
    async def stop() -> StateOut:
        return StateOut.from_domain(await service.stop())

    @app.websocket("/ws/movement")
    async def movement(ws: WebSocket) -> None:
        """Continuous movement channel.

        MVP: each message ``{"direction": "north", "distance_meters": 1}`` performs one
        step and echoes back the new state. This establishes the transport that the
        joystick/WASD loop (a later milestone) will drive at a fixed tick rate.
        """
        await ws.accept()
        try:
            while True:
                msg = await ws.receive_json()
                try:
                    command = StepCommand(
                        parse_direction(msg["direction"]), float(msg["distance_meters"])
                    )
                    state = await service.step(command)
                    out = StateOut.from_domain(state).model_dump(mode="json")
                    await ws.send_json({"ok": True, "state": out})
                except (KeyError, ValueError) as exc:
                    await ws.send_json({"ok": False, "error": str(exc)})
                except EngineError as exc:
                    await ws.send_json({"ok": False, "error": exc.message, "code": exc.code.value})
        except WebSocketDisconnect:
            return

    # Keep an accessor so a server wrapper can release backend resources on shutdown.
    app.state.service = service
    return app
