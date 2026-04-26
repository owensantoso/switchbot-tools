#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from types import SimpleNamespace
import uuid

from switchbot import GetSwitchbotDevices, SwitchbotBulb, SwitchbotLightStrip


CACHE_FILE = Path.home() / ".switchbot_ble_lights.json"
DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "switchbot-ble.jsonl"


def _wall_clock() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class BleEventLogger:
    def __init__(
        self,
        *,
        enabled: bool,
        log_path: Path,
        run_id: str | None = None,
        wall_clock: Any = _wall_clock,
        perf_counter: Any = time.perf_counter,
    ) -> None:
        self.enabled = enabled
        self.log_path = log_path
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.wall_clock = wall_clock
        self.perf_counter = perf_counter
        self._started = perf_counter()

    def event(self, event: str, **fields: Any) -> None:
        now = self.perf_counter()
        payload = {
            "timestamp": self.wall_clock(),
            "run_id": self.run_id,
            "event": event,
            "elapsed_ms": round((now - self._started) * 1000, 1),
            **fields,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        if self.enabled:
            detail = " ".join(f"{key}={value}" for key, value in fields.items())
            suffix = f" {detail}" if detail else ""
            print(f"[ble][{payload['timestamp']}] {event}{suffix}", file=sys.stderr)


def resolve_log_path(configured: str | None) -> Path:
    if configured:
        return Path(configured)
    from_env = os.environ.get("SWITCHBOT_BLE_LOG_PATH")
    if from_env:
        return Path(from_env)
    return DEFAULT_LOG_PATH


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


async def scan(timeout: int, logger: BleEventLogger) -> int:
    started = time.monotonic()
    logger.event("scan_started", timeout=timeout)
    try:
        logger.event("scan_discover_started", timeout=timeout)
        devices = await GetSwitchbotDevices().discover(scan_timeout=timeout)
        logger.event("scan_discover_finished", timeout=timeout, device_count=len(devices))
    except Exception as exc:
        logger.event("scan_failed", timeout=timeout, error=str(exc))
        print(f"BLE scan failed: {exc}", file=sys.stderr)
        return 1

    results = [serialize_scan_result(address, adv) for address, adv in devices.items()]
    save_light_cache(results, logger=logger)
    print(json.dumps(results, indent=2))
    logger.event(
        "scan_finished",
        timeout=timeout,
        duration_s=round(time.monotonic() - started, 3),
        device_count=len(results),
        cache_path=str(CACHE_FILE),
    )
    return 0


def is_light_adv(adv: Any) -> bool:
    return adv.data.get("model") in {"u", "r"}


def class_for_adv(adv: Any) -> Any:
    return SwitchbotBulb if adv.data.get("model") == "u" else SwitchbotLightStrip


async def discover(timeout: int, logger: BleEventLogger) -> dict[str, Any]:
    logger.event("discover_started", timeout=timeout)
    devices = await GetSwitchbotDevices().discover(scan_timeout=timeout)
    logger.event("discover_finished", timeout=timeout, device_count=len(devices))
    return devices


def save_light_cache(results: list[dict[str, Any]], *, logger: BleEventLogger | None = None) -> None:
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
    if logger is not None:
        logger.event("cache_save_started", cache_path=str(CACHE_FILE), light_count=len(lights))
    CACHE_FILE.write_text(json.dumps(lights, indent=2), encoding="utf-8")
    if logger is not None:
        logger.event("cache_save_finished", cache_path=str(CACHE_FILE), light_count=len(lights))


def load_light_cache(*, logger: BleEventLogger | None = None) -> list[dict[str, Any]]:
    if logger is not None:
        logger.event("cache_load_started", cache_path=str(CACHE_FILE))
    if not CACHE_FILE.exists():
        if logger is not None:
            logger.event("cache_load_finished", cache_path=str(CACHE_FILE), light_count=0, cache_exists=False)
        return []
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        if logger is not None:
            logger.event("cache_load_failed", cache_path=str(CACHE_FILE), error="invalid_json")
        return []
    if not isinstance(data, list):
        if logger is not None:
            logger.event("cache_load_failed", cache_path=str(CACHE_FILE), error="unexpected_payload")
        return []
    lights = [item for item in data if isinstance(item, dict) and item.get("address") and item.get("model") in {"u", "r"}]
    if logger is not None:
        logger.event("cache_load_finished", cache_path=str(CACHE_FILE), light_count=len(lights), cache_exists=True)
    return lights


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


async def first_device_of_model(model_code: str, timeout: int, address: str | None, logger: BleEventLogger) -> Any | None:
    logger.event("first_device_lookup_started", model_code=model_code, timeout=timeout, address=address or "")
    devices = await discover(timeout, logger)
    if address:
        target = address.upper()
        for adv in devices.values():
            if adv.device.address.upper() == target:
                logger.event("first_device_lookup_finished", model_code=model_code, matched="address", address=adv.device.address)
                return adv
    for adv in devices.values():
        if adv.data.get("model") == model_code:
            logger.event("first_device_lookup_finished", model_code=model_code, matched="model", address=adv.device.address)
            return adv
    logger.event("first_device_lookup_finished", model_code=model_code, matched="none")
    return None


async def perform_action(device: Any, adv: Any, args: argparse.Namespace, logger: BleEventLogger) -> bool:
    logger.event(
        "device_action_started",
        action=args.action,
        device_name=adv.device.name,
        address=adv.device.address,
    )
    if args.action == "on":
        result = await device.turn_on()
    elif args.action == "off":
        result = await device.turn_off()
    elif args.action == "brightness":
        result = await device.set_brightness(args.value)
    elif args.action == "temp":
        result = await device.set_color_temp(args.brightness, args.value)
    elif args.action == "color":
        result = await device.set_rgb(args.brightness, args.r, args.g, args.b)
    else:
        raise ValueError(f"Unsupported action: {args.action}")
    logger.event(
        "device_action_finished",
        action=args.action,
        device_name=adv.device.name,
        address=adv.device.address,
        ok=bool(result),
    )
    return result


async def control(args: argparse.Namespace, logger: BleEventLogger) -> int:
    started = time.monotonic()
    model_code = "u" if args.kind == "bulb" else "r"
    logger.event("control_started", kind=args.kind, action=args.action, timeout=args.timeout, address=args.address or "")
    adv = await first_device_of_model(model_code, args.timeout, args.address, logger)
    if adv is None:
        logger.event("control_failed", kind=args.kind, action=args.action, error="no_device_found")
        print(
            f"No nearby SwitchBot {args.kind} found over BLE during {args.timeout}s scan.",
            file=sys.stderr,
        )
        return 2

    cls = SwitchbotBulb if args.kind == "bulb" else SwitchbotLightStrip
    logger.event("device_object_creating", kind=args.kind, class_name=cls.__name__, address=adv.device.address)
    device = cls(device=adv.device, scan_timeout=args.timeout)
    logger.event("device_object_created", kind=args.kind, class_name=cls.__name__, address=adv.device.address)

    try:
        ok = await perform_action(device, adv, args, logger)
    except Exception as exc:
        logger.event("control_failed", kind=args.kind, action=args.action, error=str(exc), address=adv.device.address)
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
    logger.event(
        "control_finished",
        kind=args.kind,
        action=args.action,
        duration_s=round(time.monotonic() - started, 3),
        device_name=adv.device.name,
        address=adv.device.address,
        ok=bool(ok),
    )
    return 0


async def all_lights(args: argparse.Namespace, logger: BleEventLogger) -> int:
    started = time.monotonic()
    logger.event(
        "all_lights_started",
        action=args.action,
        timeout=args.timeout,
        parallel=args.parallel,
        discover=bool(args.discover),
    )
    light_advs: list[Any]
    source: str
    if args.discover:
        try:
            devices = await discover(args.timeout, logger)
        except Exception as exc:
            logger.event("all_lights_failed", action=args.action, error=str(exc), source="discovery")
            print(f"BLE scan failed: {exc}", file=sys.stderr)
            return 1
        results = [serialize_scan_result(address, adv) for address, adv in devices.items()]
        save_light_cache(results, logger=logger)
        light_advs = [adv for adv in devices.values() if is_light_adv(adv)]
        source = "discovery"
    else:
        cached = load_light_cache(logger=logger)
        light_advs = [adv_from_cache(item) for item in cached]
        source = "cache"
    if not light_advs:
        logger.event("all_lights_failed", action=args.action, error="no_lights_found", source=source)
        hint = "Run with --discover once to refresh the local BLE cache."
        print(
            f"No cached SwitchBot BLE lights available. {hint}" if source == "cache"
            else f"No nearby SwitchBot lights found over BLE during {args.timeout}s scan.",
            file=sys.stderr,
        )
        return 2

    semaphore = asyncio.Semaphore(max(1, args.parallel))

    async def run_for_adv(adv: Any) -> dict[str, Any]:
        queued_at = time.monotonic()
        logger.event(
            "device_task_queued",
            action=args.action,
            device_name=adv.device.name,
            address=adv.device.address,
            source=source,
        )
        async with semaphore:
            action_started = time.monotonic()
            logger.event(
                "device_task_acquired",
                action=args.action,
                device_name=adv.device.name,
                address=adv.device.address,
                waited_ms=round((action_started - queued_at) * 1000, 1),
            )
            cls = class_for_adv(adv)
            logger.event(
                "device_object_creating",
                action=args.action,
                device_name=adv.device.name,
                address=adv.device.address,
                class_name=cls.__name__,
            )
            device = cls(device=adv.device, scan_timeout=args.timeout)
            logger.event(
                "device_object_created",
                action=args.action,
                device_name=adv.device.name,
                address=adv.device.address,
                class_name=cls.__name__,
            )
            try:
                ok = await perform_action(device, adv, args, logger)
                result = {
                    "ok": ok,
                    "action": args.action,
                    "device": {
                        "name": adv.device.name,
                        "address": adv.device.address,
                        "rssi": adv.rssi,
                    },
                }
                logger.event(
                    "device_task_finished",
                    action=args.action,
                    device_name=adv.device.name,
                    address=adv.device.address,
                    duration_ms=round((time.monotonic() - action_started) * 1000, 1),
                    ok=bool(ok),
                )
                return result
            except Exception as exc:
                logger.event(
                    "device_task_failed",
                    action=args.action,
                    device_name=adv.device.name,
                    address=adv.device.address,
                    duration_ms=round((time.monotonic() - action_started) * 1000, 1),
                    error=str(exc),
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
    logger.event(
        "all_lights_finished",
        action=args.action,
        source=source,
        total_elapsed_s=round(time.monotonic() - started, 3),
        failures=failures,
        light_count=len(light_advs),
        log_path=str(logger.log_path),
    )
    return 0 if failures == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Direct local BLE SwitchBot tester")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan for nearby SwitchBot BLE devices")
    p_scan.add_argument("--timeout", type=int, default=3)
    p_scan.add_argument("--debug", "--verbose", "-v", action="store_true", dest="verbose")
    p_scan.add_argument("--jsonl-path")

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
    p_control.add_argument("--debug", "--verbose", "-v", action="store_true", dest="verbose")
    p_control.add_argument("--jsonl-path")

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
    p_all.add_argument("--debug", "--verbose", "-v", action="store_true", dest="verbose")
    p_all.add_argument("--jsonl-path")

    return parser


async def main_async() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logger = BleEventLogger(
        enabled=bool(getattr(args, "verbose", False)),
        log_path=resolve_log_path(getattr(args, "jsonl_path", None)),
    )
    logger.event(
        "command_invoked",
        cmd=args.cmd,
        argv=sys.argv[1:],
        cache_path=str(CACHE_FILE),
        log_path=str(logger.log_path),
    )

    if args.cmd == "scan":
        return await scan(args.timeout, logger)
    if args.cmd == "control":
        return await control(args, logger)
    if args.cmd == "all":
        return await all_lights(args, logger)
    return 2


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
