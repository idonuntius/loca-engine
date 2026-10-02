"""Device enumeration via usbmux + lockdown.

``usbmux.list_devices()`` gives us the UDID and connection type for everything plugged
in. We then try to enrich each entry with lockdown values (name, model, iOS version).
Enrichment is best-effort: an untrusted or locked device still appears in the list
with just its UDID, rather than vanishing or raising.
"""

from __future__ import annotations

import logging

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.usbmux import list_devices as usbmux_list_devices

from ...domain.models import ConnectionType, DeviceSummary

logger = logging.getLogger(__name__)


def _connection_type(raw: str | None) -> ConnectionType:
    if raw is None:
        return ConnectionType.UNKNOWN
    value = raw.lower()
    if "usb" in value:
        return ConnectionType.USB
    if "network" in value or "wifi" in value:
        return ConnectionType.WIFI
    return ConnectionType.UNKNOWN


async def list_devices() -> list[DeviceSummary]:
    summaries: list[DeviceSummary] = []
    for mux_device in await usbmux_list_devices():
        udid = getattr(mux_device, "serial", None) or getattr(mux_device, "udid", "")
        connection = _connection_type(getattr(mux_device, "connection_type", None))
        summaries.append(await _summarize(udid, connection))
    return summaries


async def _summarize(udid: str, connection: ConnectionType) -> DeviceSummary:
    # autopair=False: never trigger a trust prompt just to list devices.
    try:
        lockdown = await create_using_usbmux(serial=udid, autopair=False)
    except Exception as exc:  # noqa: BLE001 - untrusted/locked device is normal here
        logger.debug("lockdown enrichment skipped for %s: %s", udid, exc)
        return DeviceSummary(udid=udid, name=udid, connection_type=connection)

    def value(key: str) -> str | None:
        try:
            return lockdown.all_values.get(key)
        except Exception:  # noqa: BLE001
            return None

    name = value("DeviceName") or udid
    return DeviceSummary(
        udid=udid,
        name=name,
        product_type=value("ProductType"),
        # Marketing name ("iPhone 15 Pro") is not available offline; leave it to the
        # client to map from product_type rather than guess here.
        marketing_name=None,
        ios_version=value("ProductVersion"),
        build_version=value("BuildVersion"),
        connection_type=connection,
    )
