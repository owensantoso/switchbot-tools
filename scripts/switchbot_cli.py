#!/usr/bin/env python3
"""
Small SwitchBot CLI for listing devices and controlling supported lights.

Authentication:
  export SWITCHBOT_TOKEN="..."
  export SWITCHBOT_SECRET="..."

Examples:
  python3 switchbot_cli.py devices
  python3 switchbot_cli.py status <device_id>
  python3 switchbot_cli.py on <device_id>
  python3 switchbot_cli.py brightness <device_id> 35
  python3 switchbot_cli.py color <device_id> 255 120 0
  python3 switchbot_cli.py temp <device_id> 4000
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from typing import Any
from urllib import error, request


API_BASE = "https://api.switch-bot.com/v1.1"


def build_headers(token: str, secret: str) -> dict[str, str]:
    nonce = str(uuid.uuid4())
    timestamp = str(int(time.time() * 1000))
    payload = f"{token}{timestamp}{nonce}".encode("utf-8")
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    ).decode("utf-8")
    return {
        "Authorization": token,
        "sign": signature,
        "nonce": nonce,
        "t": timestamp,
        "Content-Type": "application/json",
    }


def require_creds() -> tuple[str, str]:
    token = os.environ.get("SWITCHBOT_TOKEN")
    secret = os.environ.get("SWITCHBOT_SECRET")
    if not token or not secret:
        print(
            "Missing credentials. Set SWITCHBOT_TOKEN and SWITCHBOT_SECRET in your shell.",
            file=sys.stderr,
        )
        sys.exit(2)
    return token, secret


def api_request(
    method: str,
    path: str,
    token: str,
    secret: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, method=method, headers=build_headers(token, secret))
    try:
        with request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} from SwitchBot API: {payload}", file=sys.stderr)
        sys.exit(1)
    except error.URLError as exc:
        print(f"Network error talking to SwitchBot API: {exc}", file=sys.stderr)
        sys.exit(1)


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def command_body(command: str, parameter: str = "default") -> dict[str, str]:
    return {
        "command": command,
        "parameter": parameter,
        "commandType": "command",
    }


def list_devices(token: str, secret: str) -> None:
    resp = api_request("GET", "/devices", token, secret)
    body = resp.get("body", {})
    devices = body.get("deviceList", [])
    if not devices:
        print_json(resp)
        return
    for dev in devices:
        print(
            f"{dev.get('deviceId')}\t{dev.get('deviceType')}\t{dev.get('deviceName')}\t"
            f"cloud={dev.get('enableCloudService')}\thub={dev.get('hubDeviceId')}"
        )


def get_devices(token: str, secret: str) -> list[dict[str, Any]]:
    resp = api_request("GET", "/devices", token, secret)
    return resp.get("body", {}).get("deviceList", [])


def resolve_device_id(token: str, secret: str, target: str) -> str:
    devices = get_devices(token, secret)
    normalized = target.strip().casefold()

    for dev in devices:
        if str(dev.get("deviceId", "")).casefold() == normalized:
            return str(dev["deviceId"])

    exact = [
        dev
        for dev in devices
        if str(dev.get("deviceName", "")).strip().casefold() == normalized
    ]
    if exact:
        return str(exact[0]["deviceId"])

    partial = [
        dev
        for dev in devices
        if normalized in str(dev.get("deviceName", "")).strip().casefold()
    ]
    if len(partial) == 1:
        return str(partial[0]["deviceId"])
    if not partial:
        print(f"No device found matching: {target}", file=sys.stderr)
    else:
        names = ", ".join(str(dev.get("deviceName")) for dev in partial)
        print(f"Multiple devices matched '{target}': {names}", file=sys.stderr)
    sys.exit(2)


def get_status(token: str, secret: str, device_id: str) -> None:
    print_json(api_request("GET", f"/devices/{device_id}/status", token, secret))


def send_command(token: str, secret: str, device_id: str, body: dict[str, str]) -> None:
    print_json(api_request("POST", f"/devices/{device_id}/commands", token, secret, body))


def list_scenes(token: str, secret: str) -> None:
    print_json(api_request("GET", "/scenes", token, secret))


def run_scene(token: str, secret: str, scene_id: str) -> None:
    print_json(api_request("POST", f"/scenes/{scene_id}/execute", token, secret))


def run_scene_by_name(token: str, secret: str, scene_name: str) -> None:
    resp = api_request("GET", "/scenes", token, secret)
    scenes = resp.get("body", [])
    normalized = scene_name.strip().casefold()
    exact = [scene for scene in scenes if str(scene.get("sceneName", "")).strip().casefold() == normalized]
    if exact:
        run_scene(token, secret, str(exact[0]["sceneId"]))
        return
    partial = [scene for scene in scenes if normalized in str(scene.get("sceneName", "")).strip().casefold()]
    if len(partial) == 1:
        run_scene(token, secret, str(partial[0]["sceneId"]))
        return
    if not partial:
        print(f"No scene found matching: {scene_name}", file=sys.stderr)
    else:
        names = ", ".join(str(scene.get("sceneName")) for scene in partial)
        print(f"Multiple scenes matched '{scene_name}': {names}", file=sys.stderr)
    sys.exit(2)


def iter_light_devices(token: str, secret: str) -> list[dict[str, Any]]:
    resp = api_request("GET", "/devices", token, secret)
    devices = resp.get("body", {}).get("deviceList", [])
    return [
        dev
        for dev in devices
        if dev.get("enableCloudService")
        and str(dev.get("deviceType", "")).lower() in {"color bulb", "strip light"}
    ]


def set_all_color(
    token: str,
    secret: str,
    r: int,
    g: int,
    b: int,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    devices = iter_light_devices(token, secret)

    def run_for_device(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        turn_on = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("turnOn"),
        )
        color = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setColor", f"{r}:{g}:{b}"),
        )
        bright = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setBrightness", str(brightness)),
        )
        return {
            "deviceId": device_id,
            "deviceName": name,
            "turnOn": turn_on.get("body"),
            "setColor": color.get("body"),
            "setBrightness": bright.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def set_all_rainbow(
    token: str,
    secret: str,
    brightness: int = 70,
    parallel: int = 8,
) -> None:
    devices = sorted(iter_light_devices(token, secret), key=lambda item: str(item.get("deviceName")))
    palette = [
        (255, 0, 0),
        (255, 127, 0),
        (255, 255, 0),
        (0, 200, 0),
        (0, 120, 255),
        (75, 0, 130),
        (148, 0, 211),
    ]

    def run_for_device(index_and_device: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        index, dev = index_and_device
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        r, g, b = palette[index % len(palette)]
        turn_on = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("turnOn"),
        )
        color = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setColor", f"{r}:{g}:{b}"),
        )
        bright = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setBrightness", str(brightness)),
        )
        return {
            "deviceId": device_id,
            "deviceName": name,
            "rgb": [r, g, b],
            "turnOn": turn_on.get("body"),
            "setColor": color.get("body"),
            "setBrightness": bright.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, item) for item in enumerate(devices)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def set_all_temp(
    token: str,
    secret: str,
    value: int,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    devices = iter_light_devices(token, secret)

    def run_for_device(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        turn_on = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("turnOn"),
        )
        temp = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setColorTemperature", str(value)),
        )
        bright = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setBrightness", str(brightness)),
        )
        return {
            "deviceId": device_id,
            "deviceName": name,
            "turnOn": turn_on.get("body"),
            "setColorTemperature": temp.get("body"),
            "setBrightness": bright.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def set_all_purple(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_color(token, secret, 128, 0, 128, brightness, parallel)


def set_all_white(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_temp(token, secret, 4000, brightness, parallel)


def set_all_warm_white(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_temp(token, secret, 2700, brightness, parallel)


def set_all_soft_white(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_temp(token, secret, 3000, brightness, parallel)


def set_all_neutral_white(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_temp(token, secret, 4000, brightness, parallel)


def set_all_cool_white(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_temp(token, secret, 5500, brightness, parallel)


def set_all_daylight(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_temp(token, secret, 6500, brightness, parallel)


def set_all_gold(
    token: str,
    secret: str,
    brightness: int = 100,
    parallel: int = 8,
) -> None:
    set_all_color(token, secret, 255, 190, 0, brightness, parallel)


def set_all_brightness(
    token: str,
    secret: str,
    brightness: int,
    parallel: int = 8,
) -> None:
    devices = iter_light_devices(token, secret)

    def run_for_device(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        bright = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("setBrightness", str(brightness)),
        )
        return {
            "deviceId": device_id,
            "deviceName": name,
            "setBrightness": bright.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def get_all_light_status(token: str, secret: str, parallel: int = 8) -> None:
    devices = iter_light_devices(token, secret)

    def run_for_device(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        status = api_request("GET", f"/devices/{device_id}/status", token, secret)
        return {
            "deviceId": device_id,
            "deviceName": name,
            "status": status.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def turn_all_off(token: str, secret: str, parallel: int = 8) -> None:
    devices = iter_light_devices(token, secret)

    def run_for_device(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        off = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("turnOff"),
        )
        return {
            "deviceId": device_id,
            "deviceName": name,
            "turnOff": off.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def turn_all_on(token: str, secret: str, parallel: int = 8) -> None:
    devices = iter_light_devices(token, secret)

    def run_for_device(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        on = api_request(
            "POST",
            f"/devices/{device_id}/commands",
            token,
            secret,
            command_body("turnOn"),
        )
        return {
            "deviceId": device_id,
            "deviceName": name,
            "turnOn": on.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(run_for_device, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(results)


def toggle_all(token: str, secret: str, parallel: int = 8) -> None:
    devices = iter_light_devices(token, secret)

    def fetch_status(dev: dict[str, Any]) -> dict[str, Any]:
        device_id = str(dev.get("deviceId"))
        name = str(dev.get("deviceName"))
        status = api_request("GET", f"/devices/{device_id}/status", token, secret)
        body = status.get("body", {})
        return {
            "deviceId": device_id,
            "deviceName": name,
            "power": body.get("power"),
            "online": body.get("onlineStatus"),
        }

    statuses: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(fetch_status, dev) for dev in devices]
        for future in concurrent.futures.as_completed(futures):
            statuses.append(future.result())

    on_count = sum(1 for item in statuses if str(item.get("power", "")).lower() == "on")
    off_count = len(statuses) - on_count
    action = "turnOff" if on_count > off_count else "turnOn"

    def apply_action(item: dict[str, Any]) -> dict[str, Any]:
        response = api_request(
            "POST",
            f"/devices/{item['deviceId']}/commands",
            token,
            secret,
            command_body(action),
        )
        return {
            "deviceId": item["deviceId"],
            "deviceName": item["deviceName"],
            "previousPower": item.get("power"),
            "action": action,
            "result": response.get("body"),
        }

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(apply_action, item) for item in statuses]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["deviceName"])
    print_json(
        {
            "decision": "off" if action == "turnOff" else "on",
            "onCount": on_count,
            "offCount": off_count,
            "statuses": sorted(statuses, key=lambda item: item["deviceName"]),
            "results": results,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SwitchBot terminal controller")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="List devices on the account")
    sub.add_parser("scenes", help="List manual scenes")
    p_all_brightness = sub.add_parser("all-brightness", help="Set brightness on all SwitchBot lights")
    p_all_brightness.add_argument("brightness", type=int)
    p_all_brightness.add_argument("--parallel", type=int, default=8)
    p_all_color = sub.add_parser("all-color", help="Set all SwitchBot lights to an RGB color")
    p_all_color.add_argument("r", type=int)
    p_all_color.add_argument("g", type=int)
    p_all_color.add_argument("b", type=int)
    p_all_color.add_argument("--brightness", type=int, default=100)
    p_all_color.add_argument("--parallel", type=int, default=8)
    p_all_temp = sub.add_parser("all-temp", help="Set all SwitchBot lights to a color temperature")
    p_all_temp.add_argument("value", type=int)
    p_all_temp.add_argument("--brightness", type=int, default=100)
    p_all_temp.add_argument("--parallel", type=int, default=8)
    p_all_on = sub.add_parser("all-on", help="Turn all SwitchBot lights on using their remembered state")
    p_all_on.add_argument("--parallel", type=int, default=8)
    p_all_off = sub.add_parser("all-off", help="Turn all SwitchBot lights off")
    p_all_off.add_argument("--parallel", type=int, default=8)
    p_all_toggle = sub.add_parser("all-toggle", help="Toggle all SwitchBot lights based on current state")
    p_all_toggle.add_argument("--parallel", type=int, default=8)
    p_all_status = sub.add_parser("all-status", help="Get status for all SwitchBot lights")
    p_all_status.add_argument("--parallel", type=int, default=8)
    p_all_purple = sub.add_parser("all-purple", help="Turn all SwitchBot lights on and purple")
    p_all_purple.add_argument("--brightness", type=int, default=100)
    p_all_purple.add_argument("--parallel", type=int, default=8)
    p_all_white = sub.add_parser("all-white", help="Turn all SwitchBot lights on and white")
    p_all_white.add_argument("--brightness", type=int, default=100)
    p_all_white.add_argument("--parallel", type=int, default=8)
    p_all_warm_white = sub.add_parser("all-warm-white", help="Turn all SwitchBot lights on and warm white")
    p_all_warm_white.add_argument("--brightness", type=int, default=100)
    p_all_warm_white.add_argument("--parallel", type=int, default=8)
    p_all_soft_white = sub.add_parser("all-soft-white", help="Turn all SwitchBot lights on and soft white")
    p_all_soft_white.add_argument("--brightness", type=int, default=100)
    p_all_soft_white.add_argument("--parallel", type=int, default=8)
    p_all_neutral_white = sub.add_parser("all-neutral-white", help="Turn all SwitchBot lights on and neutral white")
    p_all_neutral_white.add_argument("--brightness", type=int, default=100)
    p_all_neutral_white.add_argument("--parallel", type=int, default=8)
    p_all_cool_white = sub.add_parser("all-cool-white", help="Turn all SwitchBot lights on and cool white")
    p_all_cool_white.add_argument("--brightness", type=int, default=100)
    p_all_cool_white.add_argument("--parallel", type=int, default=8)
    p_all_daylight = sub.add_parser("all-daylight", help="Turn all SwitchBot lights on and daylight white")
    p_all_daylight.add_argument("--brightness", type=int, default=100)
    p_all_daylight.add_argument("--parallel", type=int, default=8)
    p_all_gold = sub.add_parser("all-gold", help="Turn all SwitchBot lights on and gold")
    p_all_gold.add_argument("--brightness", type=int, default=100)
    p_all_gold.add_argument("--parallel", type=int, default=8)
    p_all_rainbow = sub.add_parser("all-rainbow", help="Turn all SwitchBot lights on and spread a rainbow palette")
    p_all_rainbow.add_argument("--brightness", type=int, default=70)
    p_all_rainbow.add_argument("--parallel", type=int, default=8)

    p_status = sub.add_parser("status", help="Get device status")
    p_status.add_argument("device")

    p_scene = sub.add_parser("scene", help="Execute a manual scene by id")
    p_scene.add_argument("scene_id")

    p_scene_name = sub.add_parser("scene-name", help="Execute a manual scene by name")
    p_scene_name.add_argument("scene_name")

    for name in ("on", "off", "toggle"):
        p = sub.add_parser(name, help=f"Send {name} command")
        p.add_argument("device")

    p_brightness = sub.add_parser("brightness", help="Set brightness 1-100")
    p_brightness.add_argument("device")
    p_brightness.add_argument("value", type=int)

    p_temp = sub.add_parser("temp", help="Set color temperature 2700-6500")
    p_temp.add_argument("device")
    p_temp.add_argument("value", type=int)

    p_color = sub.add_parser("color", help="Set RGB color 0-255 0-255 0-255")
    p_color.add_argument("device")
    p_color.add_argument("r", type=int)
    p_color.add_argument("g", type=int)
    p_color.add_argument("b", type=int)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    token, secret = require_creds()

    if args.cmd == "devices":
        list_devices(token, secret)
        return
    if args.cmd == "scenes":
        list_scenes(token, secret)
        return
    if args.cmd == "all-brightness":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_brightness(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-color":
        rgb = (args.r, args.g, args.b)
        if any(v < 0 or v > 255 for v in rgb):
            parser.error("RGB values must each be between 0 and 255")
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_color(token, secret, args.r, args.g, args.b, args.brightness, args.parallel)
        return
    if args.cmd == "all-temp":
        if not 2700 <= args.value <= 6500:
            parser.error("temp must be between 2700 and 6500")
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_temp(token, secret, args.value, args.brightness, args.parallel)
        return
    if args.cmd == "all-on":
        turn_all_on(token, secret, args.parallel)
        return
    if args.cmd == "all-off":
        turn_all_off(token, secret, args.parallel)
        return
    if args.cmd == "all-toggle":
        toggle_all(token, secret, args.parallel)
        return
    if args.cmd == "all-status":
        get_all_light_status(token, secret, args.parallel)
        return
    if args.cmd == "all-purple":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_purple(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-white":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_white(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-warm-white":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_warm_white(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-soft-white":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_soft_white(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-neutral-white":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_neutral_white(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-cool-white":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_cool_white(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-daylight":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_daylight(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-gold":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_gold(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "all-rainbow":
        if not 1 <= args.brightness <= 100:
            parser.error("brightness must be between 1 and 100")
        set_all_rainbow(token, secret, args.brightness, args.parallel)
        return
    if args.cmd == "status":
        get_status(token, secret, resolve_device_id(token, secret, args.device))
        return
    if args.cmd == "scene":
        run_scene(token, secret, args.scene_id)
        return
    if args.cmd == "scene-name":
        run_scene_by_name(token, secret, args.scene_name)
        return
    if args.cmd == "on":
        send_command(token, secret, resolve_device_id(token, secret, args.device), command_body("turnOn"))
        return
    if args.cmd == "off":
        send_command(token, secret, resolve_device_id(token, secret, args.device), command_body("turnOff"))
        return
    if args.cmd == "toggle":
        send_command(token, secret, resolve_device_id(token, secret, args.device), command_body("toggle"))
        return
    if args.cmd == "brightness":
        if not 1 <= args.value <= 100:
            parser.error("brightness must be between 1 and 100")
        send_command(token, secret, resolve_device_id(token, secret, args.device), command_body("setBrightness", str(args.value)))
        return
    if args.cmd == "temp":
        if not 2700 <= args.value <= 6500:
            parser.error("temp must be between 2700 and 6500")
        send_command(
            token,
            secret,
            resolve_device_id(token, secret, args.device),
            command_body("setColorTemperature", str(args.value)),
        )
        return
    if args.cmd == "color":
        rgb = (args.r, args.g, args.b)
        if any(v < 0 or v > 255 for v in rgb):
            parser.error("RGB values must each be between 0 and 255")
        send_command(
            token,
            secret,
            resolve_device_id(token, secret, args.device),
            command_body("setColor", f"{args.r}:{args.g}:{args.b}"),
        )
        return

    parser.error(f"unsupported command: {args.cmd}")


if __name__ == "__main__":
    main()
