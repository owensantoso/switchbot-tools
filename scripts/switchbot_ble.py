#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from typing import Any
from types import SimpleNamespace

from switchbot import GetSwitchbotDevices, SwitchbotBulb, SwitchbotLightStrip


CACHE_FILE = Path.home() / ".switchbot_ble_lights.json"


def debug_log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr)


class CachedAddressDevice(str):
    def __new__(cls, address: str, name: str | None, rssi: Any) -> "CachedAddressDevice":
        obj = str.__new__(cls, address)
        obj.address = address
        obj.name = name or address
        obj.details = None
        obj.rssi = rssi
        return obj


def serialize_scan_result(address: str, adv: Any) -> dict[str, Any]:
    data = adv.data.get("data") or {}
    return {
        "address": address,
        "name": getattr(adv.device, "name", None),
        "rssi": adv.rssi,
        "model": adv.data.get("model"),
        "modelName": adv.data.get("modelName"),
        "raw": data,
    }


async def scan(timeout: int) -> int:
    started = time.monotonic()
    try:
        devices = await GetSwitchbotDevices().discover(scan_timeout=timeout)
    except Exception as exc:
        print(f"BLE scan failed: {exc}", file=sys.stderr)
        return 1

    results = [serialize_scan_result(address, adv) for address, adv in devices.items()]
    save_light_cache(results)
    print(json.dumps(results, indent=2))
    print(
        json.dumps(
            {
                "debug": {
                    "phase": "scan",
                    "timeout": timeout,
                    "duration_s": round(time.monotonic() - started, 3),
                    "device_count": len(results),
                }
            },
            indent=2,
        ),
        file=sys.stderr,
    )
    return 0


def is_light_adv(adv: Any) -> bool:
    return adv.data.get("model") in {"u", "r"}


def class_for_adv(adv: Any) -> Any:
    return SwitchbotBulb if adv.data.get("model") == "u" else SwitchbotLightStrip


async def discover(timeout: int) -> dict[str, Any]:
    return await GetSwitchbotDevices().discover(scan_timeout=timeout)


def save_light_cache(results: list[dict[str, Any]]) -> None:
    lights = [
        {
            "address": item["address"],
            "name": item.get("name"),
            "model": item.get("model"),
            "modelName": item.get("modelName"),
            "rssi": item.get("rssi"),
        }
        for item in results
        if item.get("model") in {"u", "r"}
    ]
    CACHE_FILE.write_text(json.dumps(lights, indent=2), encoding="utf-8")


def load_light_cache() -> list[dict[str, Any]]:
    if not CACHE_FILE.exists():
        return []
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("address") and item.get("model") in {"u", "r"}]


def adv_from_cache(item: dict[str, Any]) -> Any:
    device = CachedAddressDevice(
        str(item["address"]),
        item.get("name"),
        item.get("rssi"),
    )
    return SimpleNamespace(
        device=device,
        rssi=item.get("rssi"),
        data={
            "model": item.get("model"),
            "modelName": item.get("modelName"),
            "data": {},
        },
    )


async def first_device_of_model(model_code: str, timeout: int, address: str | None) -> Any | None:
    devices = await discover(timeout)
    if address:
        target = address.upper()
        for adv in devices.values():
            if adv.device.address.upper() == target:
                return adv
    for adv in devices.values():
        if adv.data.get("model") == model_code:
            return adv
    return None


async def perform_action(device: Any, adv: Any, args: argparse.Namespace) -> bool:
    if args.action == "on":
        return await device.turn_on()
    if args.action == "off":
        return await device.turn_off()
    if args.action == "brightness":
        return await device.set_brightness(args.value)
    if args.action == "temp":
        return await device.set_color_temp(args.brightness, args.value)
    if args.action == "color":
        return await device.set_rgb(args.brightness, args.r, args.g, args.b)
    raise ValueError(f"Unsupported action: {args.action}")


async def control(args: argparse.Namespace) -> int:
    started = time.monotonic()
    model_code = "u" if args.kind == "bulb" else "r"
    adv = await first_device_of_model(model_code, args.timeout, args.address)
    if adv is None:
        print(
            f"No nearby SwitchBot {args.kind} found over BLE during {args.timeout}s scan.",
            file=sys.stderr,
        )
        return 2

    cls = SwitchbotBulb if args.kind == "bulb" else SwitchbotLightStrip
    device = cls(device=adv.device, scan_timeout=args.timeout)

    try:
        debug_log(
            args.debug,
            f"[debug] action={args.action} device={adv.device.name} address={adv.device.address} phase=command_start elapsed={time.monotonic() - started:.3f}s",
        )
        ok = await perform_action(device, adv, args)
    except Exception as exc:
        print(f"BLE control failed for {adv.device.name} {adv.device.address}: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": ok,
                "action": args.action,
                "kind": args.kind,
                "device": {
                    "name": adv.device.name,
                    "address": adv.device.address,
                    "rssi": adv.rssi,
                },
            },
            indent=2,
        )
    )
    debug_log(
        args.debug,
        f"[debug] action={args.action} device={adv.device.name} phase=done total_elapsed={time.monotonic() - started:.3f}s",
    )
    return 0


async def all_lights(args: argparse.Namespace) -> int:
    started = time.monotonic()
    light_advs: list[Any]
    source: str
    if args.discover:
        try:
            debug_log(args.debug, f"[debug] phase=discover_start timeout={args.timeout}")
            devices = await discover(args.timeout)
        except Exception as exc:
            print(f"BLE scan failed: {exc}", file=sys.stderr)
            return 1
        results = [serialize_scan_result(address, adv) for address, adv in devices.items()]
        save_light_cache(results)
        light_advs = [adv for adv in devices.values() if is_light_adv(adv)]
        source = "discovery"
        debug_log(
            args.debug,
            f"[debug] phase=discover_done elapsed={time.monotonic() - started:.3f}s lights_found={len(light_advs)}",
        )
    else:
        cached = load_light_cache()
        light_advs = [adv_from_cache(item) for item in cached]
        source = "cache"
        debug_log(
            args.debug,
            f"[debug] phase=cache_load elapsed={time.monotonic() - started:.3f}s lights_found={len(light_advs)}",
        )
    if not light_advs:
        hint = "Run with --discover once to refresh the local BLE cache."
        print(
            f"No cached SwitchBot BLE lights available. {hint}" if source == "cache"
            else f"No nearby SwitchBot lights found over BLE during {args.timeout}s scan.",
            file=sys.stderr,
        )
        return 2

    semaphore = asyncio.Semaphore(max(1, args.parallel))

    async def run_for_adv(adv: Any) -> dict[str, Any]:
        async with semaphore:
            action_started = time.monotonic()
            cls = class_for_adv(adv)
            device = cls(device=adv.device, scan_timeout=args.timeout)
            try:
                debug_log(
                    args.debug,
                    f"[debug] phase=device_start action={args.action} name={adv.device.name} address={adv.device.address} rssi={adv.rssi} elapsed={action_started - started:.3f}s",
                )
                ok = await perform_action(device, adv, args)
                result = {
                    "ok": ok,
                    "action": args.action,
                    "device": {
                        "name": adv.device.name,
                        "address": adv.device.address,
                        "rssi": adv.rssi,
                    },
                }
                debug_log(
                    args.debug,
                    f"[debug] phase=device_done action={args.action} name={adv.device.name} elapsed={time.monotonic() - action_started:.3f}s ok={ok}",
                )
                return result
            except Exception as exc:
                debug_log(
                    args.debug,
                    f"[debug] phase=device_error action={args.action} name={adv.device.name} elapsed={time.monotonic() - action_started:.3f}s error={exc}",
                )
                return {
                    "ok": False,
                    "action": args.action,
                    "device": {
                        "name": adv.device.name,
                        "address": adv.device.address,
                        "rssi": adv.rssi,
                    },
                    "error": str(exc),
                }

    results = await asyncio.gather(*(run_for_adv(adv) for adv in light_advs))
    failures = sum(1 for item in results if not item.get("ok"))

    print(json.dumps(results, indent=2))
    debug_log(
        args.debug,
        f"[debug] phase=all_done action={args.action} total_elapsed={time.monotonic() - started:.3f}s failures={failures}",
    )
    return 0 if failures == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Direct local BLE SwitchBot tester")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan for nearby SwitchBot BLE devices")
    p_scan.add_argument("--timeout", type=int, default=3)

    p_control = sub.add_parser("control", help="Try direct BLE control on the first nearby bulb/strip")
    p_control.add_argument("kind", choices=["bulb", "strip"])
    p_control.add_argument("action", choices=["on", "off", "brightness", "temp", "color"])
    p_control.add_argument("--timeout", type=int, default=3)
    p_control.add_argument("--address")
    p_control.add_argument("--value", type=int)
    p_control.add_argument("--brightness", type=int, default=100)
    p_control.add_argument("--r", type=int, default=255)
    p_control.add_argument("--g", type=int, default=255)
    p_control.add_argument("--b", type=int, default=255)
    p_control.add_argument("--debug", action="store_true")

    p_all = sub.add_parser("all", help="Control all nearby SwitchBot bulbs/strips over BLE")
    p_all.add_argument("action", choices=["on", "off", "brightness", "temp", "color"])
    p_all.add_argument("--timeout", type=int, default=3)
    p_all.add_argument("--parallel", type=int, default=4)
    p_all.add_argument("--discover", action="store_true")
    p_all.add_argument("--value", type=int)
    p_all.add_argument("--brightness", type=int, default=100)
    p_all.add_argument("--r", type=int, default=255)
    p_all.add_argument("--g", type=int, default=255)
    p_all.add_argument("--b", type=int, default=255)
    p_all.add_argument("--debug", action="store_true")

    return parser


async def main_async() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "scan":
        return await scan(args.timeout)
    if args.cmd == "control":
        return await control(args)
    if args.cmd == "all":
        return await all_lights(args)
    return 2


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
