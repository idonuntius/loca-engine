#!/usr/bin/env python3
"""PoC (Phase 1): set / clear a connected iPhone's simulated location directly.

This script deliberately talks to pymobiledevice3 directly (bypassing the engine's
backend abstraction) so we can validate the *unknown* parts of the pipeline before
committing to an architecture:

  - Can we enumerate the connected device?
  - Does location simulation require an RSD tunnel / sudo on this iOS + macOS?
  - Which values can actually be sent (lat/lon only, or more)?

Usage:
    uv run python scripts/poc_set_location.py --list
    uv run python scripts/poc_set_location.py --udid <UDID> --lat 35.681236 --lon 139.767125
    uv run python scripts/poc_set_location.py --udid <UDID> --stop

NOTE: On iOS 17+, establishing the RemoteServiceDiscovery (RSD) tunnel may require
root. If a command fails with a permission/tunnel error, retry under sudo, e.g.:
    sudo $(mise which python) scripts/poc_set_location.py --udid <UDID> --lat .. --lon ..

The imports below are intentionally performed lazily and wrapped, because the exact
module paths vary across pymobiledevice3 versions. This script prints a clear,
actionable message instead of a raw traceback when the API shape differs — findings
from running it feed directly into backends/pmd3/.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _fail(message: str, *, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def list_devices() -> None:
    try:
        from pymobiledevice3.usbmux import list_devices as usbmux_list
    except Exception as exc:  # pragma: no cover - environment dependent
        _fail(f"could not import pymobiledevice3.usbmux: {exc!r}")

    # pymobiledevice3 11.x exposes list_devices() as a coroutine.
    devices = asyncio.run(usbmux_list())
    if not devices:
        print("no USB devices found (is the iPhone connected, unlocked and trusted?)")
        return
    for d in devices:
        # usbmux device objects expose .serial (UDID) and .connection_type across versions.
        udid = getattr(d, "serial", getattr(d, "udid", "?"))
        conn = getattr(d, "connection_type", "?")
        print(f"{udid}\t{conn}")


def _create_service_provider(udid: str):
    """Create a RemoteServiceDiscovery provider for the given device.

    Tries the modern (iOS 17+) tunnel-based path first. Raises SystemExit with an
    actionable message on failure so the PoC output stays readable.
    """
    try:
        from pymobiledevice3.remote.remote_service_discovery import (  # noqa: F401
            RemoteServiceDiscoveryService,
        )
        from pymobiledevice3.tunneld.api import async_get_tunneld_devices  # noqa: F401
    except Exception as exc:
        _fail(
            "could not import RSD modules from pymobiledevice3 "
            f"({exc!r}). The API path may differ for this version — "
            "record the installed version and adjust."
        )

    # The concrete wiring (tunneld vs. start-tunnel) is exactly what this PoC exists
    # to determine on this machine. We surface a clear next step rather than guess.
    _fail(
        "RSD tunnel wiring is environment-specific and must be validated interactively.\n"
        "  Next: in one terminal run `sudo python -m pymobiledevice3 remote tunneld`,\n"
        "  then re-run this script. Capture which command + privileges succeed and\n"
        "  encode that in Engine/src/loca_engine/backends/pmd3/.",
        code=2,
    )


def set_location(udid: str, lat: float, lon: float) -> None:
    provider = _create_service_provider(udid)  # noqa: F841 (raises until wired)
    # Intended shape once the provider is available:
    #   from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
    #   from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    #   with DvtSecureSocketProxyService(provider) as dvt:
    #       LocationSimulation(dvt).set(lat, lon)
    #   print(f"set location: {lat}, {lon}")
    raise SystemExit(2)


def stop(udid: str) -> None:
    provider = _create_service_provider(udid)  # noqa: F841 (raises until wired)
    #   with DvtSecureSocketProxyService(provider) as dvt:
    #       LocationSimulation(dvt).clear()
    #   print("cleared simulated location (device returns to real GPS)")
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Loca PoC: set/clear iPhone location")
    parser.add_argument("--list", action="store_true", help="list connected devices")
    parser.add_argument("--udid", help="target device UDID")
    parser.add_argument("--lat", type=float, help="latitude to set")
    parser.add_argument("--lon", type=float, help="longitude to set")
    parser.add_argument("--stop", action="store_true", help="clear simulated location")
    args = parser.parse_args(argv)

    if args.list:
        list_devices()
        return
    if not args.udid:
        _fail("--udid is required (use --list to discover it)")
    if args.stop:
        stop(args.udid)
        return
    if args.lat is None or args.lon is None:
        _fail("--lat and --lon are required to set a location")
    set_location(args.udid, args.lat, args.lon)


if __name__ == "__main__":
    main()
