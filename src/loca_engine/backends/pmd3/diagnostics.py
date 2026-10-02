"""Connection Doctor checks for the pymobiledevice3 backend.

Split in two so the backend can drive them around a single, reused RSD tunnel:

* :func:`lockdown_checks` — connected / trusted / Developer Mode / DDI (no tunnel).
* :func:`probe_dvt` — RSD tunnel + Location Simulation, using an *existing* tunnel
  endpoint (never starts its own — starting a second native tunnel conflicts with the
  one the backend already holds).

Each check is an explicit :class:`DiagnosticCheck` with a status and, when not OK, a
short remedy. Raw exception strings are never surfaced.
"""

from __future__ import annotations

import logging

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import PersonalizedImageMounter
from pymobiledevice3.usbmux import list_devices as usbmux_list_devices

from ...domain.models import DiagnosticCheck, DiagnosticStatus
from .tunnel import RsdEndpoint

logger = logging.getLogger(__name__)


def _ok(id: str, title: str, detail: str | None = None) -> DiagnosticCheck:
    return DiagnosticCheck(id=id, title=title, status=DiagnosticStatus.OK, detail=detail)


def _fail(id: str, title: str, detail: str, remedy: str) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=id, title=title, status=DiagnosticStatus.FAIL, detail=detail, remedy=remedy
    )


def _unknown(id: str, title: str, detail: str) -> DiagnosticCheck:
    return DiagnosticCheck(id=id, title=title, status=DiagnosticStatus.UNKNOWN, detail=detail)


def status_of(checks: list[DiagnosticCheck], check_id: str) -> DiagnosticStatus | None:
    return next((c.status for c in checks if c.id == check_id), None)


async def lockdown_checks(udid: str) -> list[DiagnosticCheck]:
    """Checks 1–4: connected, trusted, Developer Mode, Developer Disk Image."""
    checks: list[DiagnosticCheck] = []

    serials = {getattr(d, "serial", None) for d in await usbmux_list_devices()}
    if udid not in serials:
        checks.append(
            _fail(
                "device_connected",
                "Device connected",
                "the device is not visible over USB",
                "Reconnect the iPhone with a data-capable cable.",
            )
        )
        return checks
    checks.append(_ok("device_connected", "Device connected"))

    try:
        lockdown = await create_using_usbmux(serial=udid, autopair=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("trust check failed for %s: %s", udid, exc)
        checks.append(
            _fail(
                "trusted",
                "Trusted",
                "this Mac is not trusted by the device",
                "Unlock the iPhone and tap “Trust” when prompted, then enter the passcode.",
            )
        )
        return checks
    checks.append(_ok("trusted", "Trusted"))

    try:
        dev_mode = await lockdown.get_developer_mode_status()
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _unknown("developer_mode", "Developer Mode enabled", f"could not read: {exc}")
        )
    else:
        if dev_mode:
            checks.append(_ok("developer_mode", "Developer Mode enabled"))
        else:
            checks.append(
                _fail(
                    "developer_mode",
                    "Developer Mode enabled",
                    "Developer Mode is off",
                    "On the iPhone: Settings → Privacy & Security → Developer Mode → On, "
                    "then restart the device.",
                )
            )

    try:
        mounter = PersonalizedImageMounter(lockdown)
        mounted = await mounter.is_image_mounted(mounter.IMAGE_TYPE)
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _unknown("ddi_mounted", "Developer Disk Image ready", f"could not determine: {exc}")
        )
    else:
        if mounted:
            checks.append(_ok("ddi_mounted", "Developer Disk Image ready"))
        else:
            checks.append(
                _fail(
                    "ddi_mounted",
                    "Developer Disk Image ready",
                    "no Developer Disk Image is mounted",
                    "Open Xcode with the device connected once (or run any Xcode build) so "
                    "it mounts the Developer Disk Image.",
                )
            )

    return checks


def tunnel_unavailable_checks(detail: str) -> list[DiagnosticCheck]:
    return [
        _fail(
            "rsd_tunnel",
            "RSD tunnel available",
            detail,
            "Ensure Developer Mode is on and the device is unlocked, then retry.",
        ),
        _unknown("location_simulation", "Location Simulation available", "skipped: no tunnel"),
    ]


def services_ok_checks() -> list[DiagnosticCheck]:
    """Both services are known-good (e.g. a live simulation session already proves them)."""
    return [
        _ok("rsd_tunnel", "RSD tunnel available"),
        _ok("location_simulation", "Location Simulation available"),
    ]


async def probe_dvt(endpoint: RsdEndpoint) -> list[DiagnosticCheck]:
    """Checks 5–6 using an existing tunnel endpoint (does NOT start a tunnel)."""
    try:
        rsd = RemoteServiceDiscoveryService((endpoint.host, endpoint.port))
        async with rsd, DvtProvider(rsd) as dvt, LocationSimulation(dvt):
            return services_ok_checks()
    except Exception:  # noqa: BLE001
        return [
            _ok("rsd_tunnel", "RSD tunnel available"),
            _fail(
                "location_simulation",
                "Location Simulation available",
                "the Location Simulation service did not open",
                "Re-mount the Developer Disk Image (reconnect with Xcode) and retry.",
            ),
        ]
