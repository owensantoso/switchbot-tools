#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import uuid


SCRIPT_DIR = Path(__file__).resolve().parent
BLE_MODULE_PATH = SCRIPT_DIR / "switchbot_ble.py"
BLE_SPEC = importlib.util.spec_from_file_location("switchbot_ble", BLE_MODULE_PATH)
assert BLE_SPEC is not None and BLE_SPEC.loader is not None
switchbot_ble = importlib.util.module_from_spec(BLE_SPEC)
BLE_SPEC.loader.exec_module(switchbot_ble)

STATE_FILE = Path.home() / ".switchbot_ble_daemon.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_CONNECT_TIMEOUT = 2.0
DEFAULT_START_TIMEOUT = 8.0


def _wall_clock() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def resolve_state_file(configured: str | None) -> Path:
    return Path(configured) if configured else STATE_FILE


def build_all_request(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "command": "all",
        "action": args.action,
        "timeout": args.timeout,
        "parallel": args.parallel,
        "discover": bool(args.discover),
        "value": args.value,
        "brightness": args.brightness,
        "r": args.r,
        "g": args.g,
        "b": args.b,
        "verbose": bool(args.verbose),
        "jsonl_path": args.jsonl_path,
        "full_update": bool(args.full_update),
        "exclude_addresses": list(args.exclude_address),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent BLE daemon client for SwitchBot lights")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the persistent BLE daemon in the foreground")
    p_serve.add_argument("--host", default=DEFAULT_HOST)
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--state-file")
    p_serve.add_argument("--jsonl-path")
    p_serve.add_argument("--verbose", "-v", action="store_true")

    p_status = sub.add_parser("status", help="Show daemon status")
    p_status.add_argument("--state-file")
    p_status.add_argument("--jsonl-path")
    p_status.add_argument("--verbose", "-v", action="store_true")
    p_status.add_argument("--autostart", action="store_true")

    p_stop = sub.add_parser("stop", help="Stop a running daemon")
    p_stop.add_argument("--state-file")
    p_stop.add_argument("--jsonl-path")
    p_stop.add_argument("--verbose", "-v", action="store_true")

    p_all = sub.add_parser("all", help="Send an all-lights BLE command through the daemon")
    p_all.add_argument("action", choices=["on", "off", "brightness", "temp", "color"])
    p_all.add_argument("--timeout", type=int, default=3)
    p_all.add_argument("--parallel", type=int, default=6)
    p_all.add_argument("--discover", action="store_true")
    p_all.add_argument("--value", type=int)
    p_all.add_argument("--brightness", type=int, default=100)
    p_all.add_argument("--r", type=int, default=255)
    p_all.add_argument("--g", type=int, default=255)
    p_all.add_argument("--b", type=int, default=255)
    p_all.add_argument("--verbose", "-v", action="store_true")
    p_all.add_argument("--jsonl-path")
    p_all.add_argument("--full-update", action="store_true")
    p_all.add_argument("--exclude-address", action="append", default=[])
    p_all.add_argument("--autostart", action="store_true")
    p_all.add_argument("--state-file")

    return parser


def load_state(state_file: Path) -> dict[str, Any] | None:
    if not state_file.exists():
        return None
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def save_state(state_file: Path, payload: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def remove_state(state_file: Path) -> None:
    with suppress(FileNotFoundError):
        state_file.unlink()


def build_client_logger(args: argparse.Namespace) -> Any:
    return switchbot_ble.BleEventLogger(
        enabled=bool(getattr(args, "verbose", False)),
        log_path=switchbot_ble.resolve_log_path(getattr(args, "jsonl_path", None)),
    )


def _connection_refused(exc: BaseException) -> bool:
    return isinstance(exc, (ConnectionRefusedError, TimeoutError, socket.timeout, OSError))


def send_request(
    state_file: Path,
    payload: dict[str, Any],
    *,
    logger: Any,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
) -> dict[str, Any]:
    state = load_state(state_file)
    if not state:
        raise FileNotFoundError(f"Daemon state file not found: {state_file}")
    host = state.get("host", DEFAULT_HOST)
    port = int(state["port"])
    payload = {**payload, "token": state["token"]}
    logger.event("daemon_request_started", request_command=payload.get("command"), host=host, port=port)
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buffer = b""
            while b"\n" not in buffer:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer += chunk
    except Exception as exc:
        logger.event("daemon_request_failed", request_command=payload.get("command"), error=str(exc))
        raise

    if not buffer:
        raise RuntimeError("Daemon returned no response")
    response = json.loads(buffer.decode("utf-8").splitlines()[0])
    logger.event(
        "daemon_request_finished",
        request_command=payload.get("command"),
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        ok=bool(response.get("ok", False)),
    )
    return response


def spawn_daemon(
    args: argparse.Namespace,
    *,
    state_file: Path,
    logger: Any,
    start_timeout: float = DEFAULT_START_TIMEOUT,
) -> None:
    logger.event("daemon_autostart_started", state_file=str(state_file))
    remove_state(state_file)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "serve",
        "--host",
        DEFAULT_HOST,
        "--port",
        "0",
        "--state-file",
        str(state_file),
    ]
    if getattr(args, "jsonl_path", None):
        command += ["--jsonl-path", args.jsonl_path]
    if getattr(args, "verbose", False):
        command += ["--verbose"]
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": str(SCRIPT_DIR.parent),
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(command, **popen_kwargs)

    deadline = time.monotonic() + start_timeout
    while time.monotonic() < deadline:
        state = load_state(state_file)
        if state and state.get("port") and state.get("token"):
            try:
                response = send_request(
                    state_file,
                    {"command": "status"},
                    logger=logger,
                    timeout=1.0,
                )
                if response.get("ok"):
                    logger.event("daemon_autostart_finished", state_file=str(state_file), port=state["port"])
                    return
            except Exception:
                pass
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for BLE daemon to start via {state_file}")


def request_with_autostart(
    args: argparse.Namespace,
    payload: dict[str, Any],
    *,
    logger: Any,
    state_file: Path,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
) -> dict[str, Any]:
    try:
        return send_request(state_file, payload, logger=logger, timeout=timeout)
    except Exception as exc:
        if not getattr(args, "autostart", False) or not _connection_refused(exc):
            raise
    spawn_daemon(args, state_file=state_file, logger=logger)
    return send_request(state_file, payload, logger=logger, timeout=timeout)


class DeviceEntry:
    def __init__(self, adv: Any, device: Any, class_name: str, created_at: float) -> None:
        self.adv = adv
        self.device = device
        self.class_name = class_name
        self.created_at = created_at


class DaemonRuntime:
    def __init__(self, *, state_file: Path, logger: Any, disconnect_delay: float) -> None:
        self.state_file = state_file
        self.logger = logger
        self.disconnect_delay = disconnect_delay
        self.device_entries: dict[str, DeviceEntry] = {}
        self.cached_advs: dict[str, Any] = {}
        self._request_lock = asyncio.Lock()
        self._server: asyncio.AbstractServer | None = None

        # Keep underlying BLE clients warm for longer between commands.
        device_module = sys.modules.get("switchbot.devices.device")
        if device_module is not None:
            setattr(device_module, "DISCONNECT_DELAY", disconnect_delay)

    async def _load_advs(self, *, discover: bool, timeout: int) -> tuple[list[Any], str]:
        if discover:
            devices = await switchbot_ble.discover(timeout, self.logger)
            results = [switchbot_ble.serialize_scan_result(address, adv) for address, adv in devices.items()]
            switchbot_ble.save_light_cache(results, logger=self.logger)
            advs = [adv for adv in devices.values() if switchbot_ble.is_light_adv(adv)]
            self.cached_advs = {
                switchbot_ble.format_mac_upper(str(adv.device.address)): adv for adv in advs
            }
            return advs, "discovery"

        if self.cached_advs:
            return list(self.cached_advs.values()), "memory"

        cached = switchbot_ble.load_light_cache(logger=self.logger)
        advs = [switchbot_ble.adv_from_cache(item) for item in cached]
        self.cached_advs = {
            switchbot_ble.format_mac_upper(str(adv.device.address)): adv for adv in advs
        }
        return advs, "cache"

    def _get_or_create_device(self, adv: Any, *, timeout: int) -> tuple[Any, bool]:
        address = switchbot_ble.format_mac_upper(str(adv.device.address))
        cls = switchbot_ble.class_for_adv(adv)
        existing = self.device_entries.get(address)
        if existing is not None:
            existing.adv = adv
            existing.device._device = adv.device
            existing.device._scan_timeout = timeout
            return existing.device, True
        device = cls(device=adv.device, scan_timeout=timeout)
        self.device_entries[address] = DeviceEntry(
            adv=adv,
            device=device,
            class_name=cls.__name__,
            created_at=time.monotonic(),
        )
        return device, False

    async def _run_all(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_started = time.monotonic()
        discover = bool(payload.get("discover"))
        timeout = int(payload.get("timeout", 3))
        parallel = max(1, int(payload.get("parallel", 6)))
        excluded_addresses = switchbot_ble.resolve_excluded_addresses(payload.get("exclude_addresses"))
        self.logger.event(
            "daemon_all_started",
            action=payload["action"],
            discover=discover,
            timeout=timeout,
            parallel=parallel,
            excluded_count=len(excluded_addresses),
        )
        advs, source = await self._load_advs(discover=discover, timeout=timeout)
        if excluded_addresses:
            advs = [
                adv for adv in advs
                if switchbot_ble.format_mac_upper(str(adv.device.address)) not in excluded_addresses
            ]
        if not advs:
            return {
                "ok": False,
                "exit_code": 2,
                "error": "no_lights_found",
                "results": [],
            }

        semaphore = asyncio.Semaphore(parallel)
        created_devices = 0
        reused_devices = 0

        async def run_for_adv(adv: Any) -> dict[str, Any]:
            nonlocal created_devices, reused_devices
            queued_at = time.monotonic()
            async with semaphore:
                action_started = time.monotonic()
                device, reused = self._get_or_create_device(adv, timeout=timeout)
                if reused:
                    reused_devices += 1
                else:
                    created_devices += 1
                self.logger.event(
                    "daemon_device_task_started",
                    action=payload["action"],
                    device_name=adv.device.name,
                    address=adv.device.address,
                    source=source,
                    reused=reused,
                    waited_ms=round((action_started - queued_at) * 1000, 1),
                )
                action_args = argparse.Namespace(
                    action=payload["action"],
                    value=payload.get("value"),
                    brightness=payload.get("brightness", 100),
                    r=payload.get("r", 255),
                    g=payload.get("g", 255),
                    b=payload.get("b", 255),
                    full_update=bool(payload.get("full_update")),
                    timeout=timeout,
                )
                try:
                    ok = await switchbot_ble.perform_action(device, adv, action_args, self.logger)
                    result = {
                        "ok": bool(ok),
                        "action": payload["action"],
                        "device": {
                            "name": adv.device.name,
                            "address": adv.device.address,
                            "rssi": adv.rssi,
                        },
                        "reused_connection": reused,
                    }
                    self.logger.event(
                        "daemon_device_task_finished",
                        action=payload["action"],
                        device_name=adv.device.name,
                        address=adv.device.address,
                        duration_ms=round((time.monotonic() - action_started) * 1000, 1),
                        reused=reused,
                        ok=bool(ok),
                    )
                    return result
                except Exception as exc:
                    self.logger.event(
                        "daemon_device_task_failed",
                        action=payload["action"],
                        device_name=adv.device.name,
                        address=adv.device.address,
                        duration_ms=round((time.monotonic() - action_started) * 1000, 1),
                        reused=reused,
                        error=str(exc),
                    )
                    return {
                        "ok": False,
                        "action": payload["action"],
                        "device": {
                            "name": adv.device.name,
                            "address": adv.device.address,
                            "rssi": adv.rssi,
                        },
                        "reused_connection": reused,
                        "error": str(exc),
                    }

        results = await asyncio.gather(*(run_for_adv(adv) for adv in advs))
        failures = sum(1 for item in results if not item.get("ok"))
        elapsed_ms = round((time.monotonic() - request_started) * 1000, 1)
        self.logger.event(
            "daemon_all_finished",
            action=payload["action"],
            source=source,
            duration_ms=elapsed_ms,
            failures=failures,
            light_count=len(advs),
            created_devices=created_devices,
            reused_devices=reused_devices,
        )
        return {
            "ok": failures == 0,
            "exit_code": 0 if failures == 0 else 1,
            "results": results,
            "meta": {
                "source": source,
                "duration_ms": elapsed_ms,
                "created_devices": created_devices,
                "reused_devices": reused_devices,
            },
        }

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._request_lock:
            command = payload.get("command")
            if command == "status":
                return {
                    "ok": True,
                    "state": {
                        "cached_devices": len(self.device_entries),
                        "known_advertisements": len(self.cached_advs),
                        "disconnect_delay": self.disconnect_delay,
                    },
                }
            if command == "stop":
                async def _shutdown() -> None:
                    await asyncio.sleep(0)
                    if self._server is not None:
                        self._server.close()
                    remove_state(self.state_file)

                asyncio.create_task(_shutdown())
                return {"ok": True, "stopping": True}
            if command == "all":
                return await self._run_all(payload)
            return {"ok": False, "exit_code": 2, "error": f"unsupported_command:{command}"}


async def serve_async(args: argparse.Namespace) -> int:
    state_file = resolve_state_file(args.state_file)
    logger = build_client_logger(args)
    disconnect_delay = float(os.environ.get("SWITCHBOT_BLE_DAEMON_DISCONNECT_DELAY", "30"))
    runtime = DaemonRuntime(state_file=state_file, logger=logger, disconnect_delay=disconnect_delay)

    token = uuid.uuid4().hex

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readline()
            if not raw:
                return
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("token") != token:
                response = {"ok": False, "exit_code": 3, "error": "unauthorized"}
            else:
                response = await runtime.handle(payload)
        except Exception as exc:
            response = {"ok": False, "exit_code": 1, "error": str(exc)}
        writer.write((json.dumps(response) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, args.host, args.port)
    runtime._server = server
    socket_info = server.sockets[0].getsockname()
    host = str(socket_info[0])
    port = int(socket_info[1])
    state = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "token": token,
        "started_at": _wall_clock(),
        "state_file": str(state_file),
        "log_path": str(logger.log_path),
    }
    save_state(state_file, state)
    logger.event("daemon_serve_started", host=host, port=port, state_file=str(state_file), disconnect_delay=disconnect_delay)
    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        raise
    finally:
        remove_state(state_file)
        logger.event("daemon_serve_stopped", host=host, port=port, state_file=str(state_file))
    return 0


def handle_status(args: argparse.Namespace) -> int:
    state_file = resolve_state_file(args.state_file)
    logger = build_client_logger(args)
    if getattr(args, "autostart", False) and not load_state(state_file):
        spawn_daemon(args, state_file=state_file, logger=logger)
    try:
        response = send_request(state_file, {"command": "status"}, logger=logger)
    except Exception as exc:
        print(json.dumps({"ok": False, "running": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


def handle_stop(args: argparse.Namespace) -> int:
    state_file = resolve_state_file(args.state_file)
    logger = build_client_logger(args)
    try:
        response = send_request(state_file, {"command": "stop"}, logger=logger)
    except Exception as exc:
        print(json.dumps({"ok": True, "stopping": False, "already_stopped": True, "error": str(exc)}, indent=2))
        return 0
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


def handle_all(args: argparse.Namespace) -> int:
    state_file = resolve_state_file(args.state_file)
    logger = build_client_logger(args)
    try:
        response = request_with_autostart(
            args,
            build_all_request(args),
            logger=logger,
            state_file=state_file,
            timeout=120.0,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(response.get("results", []), indent=2))
    meta = response.get("meta") or {}
    if getattr(args, "verbose", False):
        logger.event(
            "daemon_all_response",
            action=args.action,
            created_devices=meta.get("created_devices", 0),
            reused_devices=meta.get("reused_devices", 0),
            duration_ms=meta.get("duration_ms", 0),
            source=meta.get("source", "unknown"),
        )
    return int(response.get("exit_code", 1))


async def main_async() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "serve":
        return await serve_async(args)
    if args.command == "status":
        return handle_status(args)
    if args.command == "stop":
        return handle_stop(args)
    if args.command == "all":
        return handle_all(args)
    return 2


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
