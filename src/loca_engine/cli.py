"""`loca` command-line interface.

The CLI is a thin client of the engine's local API — exactly like the macOS app — so
there is one implementation of the actual logic. ``loca serve`` runs the engine;
the other commands talk to a running engine over loopback HTTP.

    loca serve [--port N]
    loca devices
    loca doctor [--udid UDID]
    loca set LAT LON [--udid UDID]
    loca move {north|south|east|west} METERS
    loca stop
    loca status

Non-serve commands find the engine port via ``--port`` or the ``LOCA_ENGINE_PORT``
environment variable. Only the standard library is used (no runtime HTTP dependency).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"


def _base_url(args: argparse.Namespace) -> str:
    port = args.port or os.environ.get("LOCA_ENGINE_PORT")
    if not port:
        _die("engine port unknown: pass --port or set LOCA_ENGINE_PORT (run `loca serve`)")
    return f"http://{DEFAULT_HOST}:{port}"


def _die(message: str, *, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _request(base: str, method: str, path: str, body: dict | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 - loopback only
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            err = json.loads(payload)
            remedy = f"\n  → {err['remedy']}" if err.get("remedy") else ""
            _die(f"{err.get('message', payload.decode())}{remedy}")
        except (ValueError, KeyError):
            _die(f"HTTP {exc.code}: {payload.decode(errors='replace')}")
    except urllib.error.URLError as exc:
        _die(f"cannot reach engine at {base}: {exc.reason}. Is `loca serve` running?")
    return None


def _cmd_serve(args: argparse.Namespace) -> None:
    from .api.server import run

    run(port=args.port or 0)


def _cmd_devices(args: argparse.Namespace) -> None:
    base = _base_url(args)
    devices = _request(base, "GET", "/devices")
    assert isinstance(devices, list)
    if not devices:
        print("no devices connected")
        return
    for d in devices:
        model = d.get("product_type") or "?"
        ios = d.get("ios_version") or "?"
        print(f"{d['udid']}  {d['name']}  {model}  iOS {ios}  {d['connection_type']}")


def _cmd_doctor(args: argparse.Namespace) -> None:
    base = _base_url(args)
    udid = args.udid or _first_udid(base)
    report = _request(base, "GET", f"/devices/{udid}/doctor")
    assert isinstance(report, dict)
    for c in report["checks"]:
        mark = {"ok": "✓", "fail": "✗", "warn": "!", "unknown": "?"}.get(c["status"], "?")
        line = f"  {mark} {c['title']}"
        if c["status"] != "ok" and c.get("remedy"):
            line += f"\n      → {c['remedy']}"
        print(line)
    print(f"ready: {report['ready']}")


def _cmd_set(args: argparse.Namespace) -> None:
    base = _base_url(args)
    udid = args.udid or _first_udid(base)
    state = _request(
        base,
        "POST",
        "/simulation/teleport",
        {"udid": udid, "latitude": args.latitude, "longitude": args.longitude},
    )
    _print_state(state)


def _cmd_move(args: argparse.Namespace) -> None:
    base = _base_url(args)
    state = _request(
        base,
        "POST",
        "/simulation/step",
        {"direction": args.direction, "distance_meters": args.meters},
    )
    _print_state(state)


def _cmd_stop(args: argparse.Namespace) -> None:
    base = _base_url(args)
    _print_state(_request(base, "POST", "/simulation/stop"))


def _cmd_status(args: argparse.Namespace) -> None:
    base = _base_url(args)
    _print_state(_request(base, "GET", "/simulation"))


def _first_udid(base: str) -> str:
    devices = _request(base, "GET", "/devices")
    assert isinstance(devices, list)
    if not devices:
        _die("no devices connected")
    return devices[0]["udid"]


def _print_state(state: object) -> None:
    assert isinstance(state, dict)
    loc = state.get("location")
    if loc:
        print(f"{state['status']}  {loc['latitude']:.6f}, {loc['longitude']:.6f}")
    else:
        print(state["status"])
    if state.get("note"):
        print(f"note: {state['note']}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loca", description="Loca location engine CLI")
    parser.add_argument("--port", type=int, help="engine port (default: $LOCA_ENGINE_PORT)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="run the engine API server").set_defaults(func=_cmd_serve)
    sub.add_parser("devices", help="list connected devices").set_defaults(func=_cmd_devices)

    p_doctor = sub.add_parser("doctor", help="run Connection Doctor")
    p_doctor.add_argument("--udid")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_set = sub.add_parser("set", help="teleport to latitude/longitude")
    p_set.add_argument("latitude", type=float)
    p_set.add_argument("longitude", type=float)
    p_set.add_argument("--udid")
    p_set.set_defaults(func=_cmd_set)

    p_move = sub.add_parser("move", help="step a distance in a cardinal direction")
    p_move.add_argument("direction", choices=["north", "south", "east", "west"])
    p_move.add_argument("meters", type=float)
    p_move.set_defaults(func=_cmd_move)

    sub.add_parser("stop", help="stop simulation / restore real GPS").set_defaults(func=_cmd_stop)
    sub.add_parser("status", help="show current simulation state").set_defaults(func=_cmd_status)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
