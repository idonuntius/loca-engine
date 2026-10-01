"""Explicit, modeled error states.

Raw pymobiledevice3 exception strings must never reach the UI. Backends translate
low-level failures into these typed errors; the API layer maps them to stable codes
so Swift (and CLI) can react to *kinds* of failure, not to message text.
"""

from __future__ import annotations

from enum import StrEnum


class EngineErrorCode(StrEnum):
    DEVICE_NOT_FOUND = "device_not_found"
    DEVICE_NOT_TRUSTED = "device_not_trusted"
    DEVICE_LOCKED = "device_locked"
    DEVELOPER_MODE_DISABLED = "developer_mode_disabled"
    DDI_NOT_MOUNTED = "ddi_not_mounted"
    RSD_TUNNEL_UNAVAILABLE = "rsd_tunnel_unavailable"
    PERMISSION_REQUIRED = "permission_required"  # e.g. sudo for RSD tunnel
    LOCATION_SIMULATION_UNAVAILABLE = "location_simulation_unavailable"
    SIMULATION_FAILED = "simulation_failed"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    UNKNOWN = "unknown"


class EngineError(Exception):
    """Domain-level error carrying a stable code and a user-facing remedy hint."""

    def __init__(
        self,
        code: EngineErrorCode,
        message: str,
        *,
        remedy: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy

    def to_dict(self) -> dict[str, str | None]:
        return {"code": self.code.value, "message": self.message, "remedy": self.remedy}
