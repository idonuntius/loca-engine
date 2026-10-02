"""pymobiledevice3 backend.

The one and only place that knows how a location is actually injected into a real
iPhone. Encapsulates the flow validated in the Phase 1 PoC (see
``docs/milestones/M1-poc-location-injection.md``):

    native RSD tunnel (no root)  →  RemoteServiceDiscoveryService
        →  DvtProvider  →  LocationSimulation.set / .clear
"""

from .backend import Pmd3Backend

__all__ = ["Pmd3Backend"]
