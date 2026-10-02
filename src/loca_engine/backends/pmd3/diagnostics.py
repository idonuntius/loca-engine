"""Connection Doctor checks for the pymobiledevice3 backend.

Each check is an explicit :class:`DiagnosticCheck` with a status and, when not OK, a
short remedy telling the user what to do next. We never surface raw exception strings:
low-level failures are caught and mapped to a human sentence.

Order mirrors the dependency chain a device must satisfy to simulate location:
connected → trusted → Developer Mode → Developer Disk Image → RSD tunnel → LocationSim.
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
from .tunnel import NativeTunnel

logger = logging.getLogger(__name__)


def _ok(id: str, title: str, detail: str | None = None) -> DiagnosticCheck:
    return DiagnosticCheck(id=id, title=title, status=DiagnosticStatus.OK, detail=detail)


def _fail(id: str, title: str, detail: str, remedy: str) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=id, title=title, status=DiagnosticStatus.FAIL, detail=detail, remedy=remedy
    )


def _unknown(id: str, title: str, detail: str) -> DiagnosticCheck:
    return DiagnosticCheck(id=id, title=title, status=DiagnosticStatus.UNKNOWN, detail=detail)


async def diagnose(udid: str, *, probe_services: bool = True) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []

    # 1. Device connected (present on usbmux)?
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

    # 2. Trusted / paired? (do not trigger a trust prompt here)
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

    # 3. Developer Mode enabled?
    try:
        dev_mode = await lockdown.get_developer_mode_status()
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _unknown("developer_mode", "Developer Mode enabled", f"could not read: {exc}")
        )
        dev_mode = None
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

    # 4. Developer Disk Image mounted? (iOS 17+ personalized image)
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

    # 5 & 6. RSD tunnel + Location Simulation. Only probe if asked (it's heavy and
    # must not run while a live session already holds the tunnel).
    if not probe_services:
        checks.append(_unknown("rsd_tunnel", "RSD tunnel available", "not probed (session active)"))
        checks.append(
            _unknown("location_simulation", "Location Simulation available", "not probed")
        )
        return checks

    checks.extend(await _probe_services())
    return checks


async def _probe_services() -> list[DiagnosticCheck]:
    """Actually open a short-lived tunnel + DVT channel to prove they work."""
    tunnel = NativeTunnel()
    try:
        endpoint = await tunnel.start()
    except Exception as exc:  # noqa: BLE001
        return [
            _fail(
                "rsd_tunnel",
                "RSD tunnel available",
                "could not establish the RSD tunnel",
                "Ensure Developer Mode is on and the device is unlocked, then retry.",
            ),
            _unknown("location_simulation", "Location Simulation available", f"skipped: {exc}"),
        ]
    try:
        rsd = RemoteServiceDiscoveryService((endpoint.host, endpoint.port))
        async with rsd, DvtProvider(rsd) as dvt, LocationSimulation(dvt):
            return [
                _ok("rsd_tunnel", "RSD tunnel available"),
                _ok("location_simulation", "Location Simulation available"),
            ]
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
    finally:
        await tunnel.stop()
