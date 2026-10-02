#!/usr/bin/env python3
"""PoC (Phase 1): set / clear a connected iPhone's simulated location.

Validated end-to-end on 2026-10-02 against iPhone 15 Pro / iOS 26.5.2 with
pymobiledevice3 11.20.2 on macOS 27 (Apple Silicon). Findings:

  * Device enumeration: ``pymobiledevice3.usbmux.list_devices()`` is a *coroutine*
    in 11.x and must be awaited.
  * iOS 17+ needs a RemoteServiceDiscovery (RSD) tunnel. On macOS the
    ``remote start-tunnel --native`` path piggybacks Apple's own tunnel and needs
    **no root / sudo**. It prints ``RSD Address`` + ``RSD Port`` and must stay alive.
  * ``developer dvt simulate-location set --rsd <host> <port> -- <lat> <lon>`` is a
    *holding* command: it keeps the DVT LocationSimulation channel open while it
    runs. ``... simulate-location clear`` restores the real GPS fix.

This script wraps that proven CLI flow so Phase 1 is reproducible. The engine's
``backends/pmd3/`` will later use the in-process Python API instead
(RemoteServiceDiscoveryService + DtxServiceProvider + LocationSimulation) so a
single long-lived session can be re-targeted for teleport / movement.

Usage:
    uv run python scripts/poc_set_location.py --list
    uv run python scripts/poc_set_location.py --lat 35.681236 --lon 139.767125
        (holds the location until Ctrl-C, then clears automatically)
    uv run python scripts/poc_set_location.py --stop
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
import time

PMD3 = [sys.executable, "-m", "pymobiledevice3"]
_RSD_ADDR = re.compile(r"RSD Address:\s*(\S+)")
_RSD_PORT = re.compile(r"RSD Port:\s*(\d+)")


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
        udid = getattr(d, "serial", getattr(d, "udid", "?"))
        conn = getattr(d, "connection_type", "?")
        print(f"{udid}\t{conn}")


class NativeTunnel:
    """Context manager for a root-free macOS native RSD tunnel.

    Spawns ``pymobiledevice3 remote start-tunnel --native`` and parses the printed
    ``RSD Address`` / ``RSD Port``. The subprocess is kept alive for the duration of
    the ``with`` block and terminated on exit.
    """

    def __init__(self, udid: str | None = None) -> None:
        self._udid = udid
        self._proc: subprocess.Popen[str] | None = None
        self.host: str = ""
        self.port: int = 0

    def __enter__(self) -> NativeTunnel:
        cmd = [*PMD3, "remote", "start-tunnel", "--native"]
        if self._udid:
            cmd += ["--udid", self._udid]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        deadline = time.monotonic() + 30
        assert self._proc.stdout is not None
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                if self._proc.poll() is not None:
                    break
                continue
            if (m := _RSD_ADDR.search(line)) and not self.host:
                self.host = m.group(1)
            if (m := _RSD_PORT.search(line)) and not self.port:
                self.port = int(m.group(1))
            if self.host and self.port:
                return self
        self.__exit__(None, None, None)
        _fail(
            "could not establish native RSD tunnel. Ensure the iPhone is unlocked, "
            "trusted, and Developer Mode is enabled."
        )
        return self  # unreachable

    def __exit__(self, *exc: object) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _simulate(args: list[str], host: str, port: int) -> subprocess.CompletedProcess[str]:
    cmd = [*PMD3, "developer", "dvt", "simulate-location", *args, "--rsd", host, str(port)]
    return subprocess.run(cmd, text=True)


def set_location(udid: str | None, lat: float, lon: float) -> None:
    with NativeTunnel(udid) as tunnel:
        print(f"tunnel up: rsd {tunnel.host} {tunnel.port}")
        print(f"setting location: {lat}, {lon}  (Ctrl-C to clear and exit)")
        try:
            # `set` holds the DVT channel open; it blocks until interrupted.
            _simulate(["set", "--", str(lat), str(lon)], tunnel.host, tunnel.port)
        except KeyboardInterrupt:
            pass
        finally:
            print("\nclearing simulated location...")
            _simulate(["clear"], tunnel.host, tunnel.port)
            print("cleared (device returns to real GPS)")


def stop(udid: str | None) -> None:
    with NativeTunnel(udid) as tunnel:
        _simulate(["clear"], tunnel.host, tunnel.port)
        print("cleared simulated location (device returns to real GPS)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Loca PoC: set/clear iPhone location")
    parser.add_argument("--list", action="store_true", help="list connected devices")
    parser.add_argument("--udid", help="target device UDID (default: first USB device)")
    parser.add_argument("--lat", type=float, help="latitude to set")
    parser.add_argument("--lon", type=float, help="longitude to set")
    parser.add_argument("--stop", action="store_true", help="clear simulated location")
    args = parser.parse_args(argv)

    if args.list:
        list_devices()
        return
    if args.stop:
        stop(args.udid)
        return
    if args.lat is None or args.lon is None:
        _fail("--lat and --lon are required to set a location (or use --list / --stop)")
    set_location(args.udid, args.lat, args.lon)


if __name__ == "__main__":
    main()
