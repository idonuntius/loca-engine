"""Run the engine's local API server.

Binds to loopback (``127.0.0.1``) only — never an external interface — so the
authentication-free API is not reachable from the network. Port 0 asks the OS for a
free port; the chosen port is printed as a line ``LOCA_ENGINE_PORT=<n>`` so a parent
process (the macOS app) can read it from stdout.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from ..backends.pmd3 import Pmd3Backend
from ..location.service import SimulationService
from .app import create_app

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"


def build_app() -> tuple[FastAPI, Pmd3Backend]:
    backend = Pmd3Backend()
    service = SimulationService(backend)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # On shutdown, best-effort clear the simulated location and release the
            # tunnel so the device returns to real GPS.
            await backend.aclose()

    app = create_app(service, lifespan=lifespan)
    return app, backend


def run(host: str = LOOPBACK, port: int = 0) -> None:
    if host not in (LOOPBACK, "localhost"):
        raise ValueError(f"refusing to bind engine API to non-loopback host: {host!r}")

    app, _backend = build_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    # Report the actually-bound port once the socket is open.
    original_startup = server.startup

    async def startup_and_announce(*args, **kwargs):  # type: ignore[no-untyped-def]
        await original_startup(*args, **kwargs)
        for srv in server.servers:
            for sock in srv.sockets:
                print(f"LOCA_ENGINE_PORT={sock.getsockname()[1]}", flush=True)

    server.startup = startup_and_announce  # type: ignore[method-assign]
    server.run()


if __name__ == "__main__":
    run()
