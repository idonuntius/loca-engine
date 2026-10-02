"""Local HTTP/WebSocket API.

A thin transport over :class:`loca_engine.location.service.SimulationService`. REST
handles one-shot operations (devices, doctor, teleport, step, stop); a WebSocket
handles continuous movement. Binds to loopback only — see ``server.py``.
"""

from .app import create_app

__all__ = ["create_app"]
