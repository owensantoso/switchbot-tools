import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "switchbot_ble.py"
SPEC = importlib.util.spec_from_file_location("switchbot_ble", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
switchbot_ble = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switchbot_ble)


class BleLoggingTests(unittest.TestCase):
    def test_ble_event_logger_writes_timestamped_jsonl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ble.jsonl"
            logger = switchbot_ble.BleEventLogger(
                enabled=True,
                log_path=path,
                run_id="run-123",
                wall_clock=lambda: "2026-04-27T05:00:00.000+09:00",
                perf_counter=lambda: 10.5,
            )

            logger.event("device_action_started", device="Desk lamp", action="on")

            payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["run_id"], "run-123")
            self.assertEqual(payload["timestamp"], "2026-04-27T05:00:00.000+09:00")
            self.assertEqual(payload["event"], "device_action_started")
            self.assertEqual(payload["elapsed_ms"], 0.0)
            self.assertEqual(payload["device"], "Desk lamp")
            self.assertEqual(payload["action"], "on")

    def test_parser_accepts_verbose_and_jsonl_path_for_all_mode(self) -> None:
        parser = switchbot_ble.build_parser()

        args = parser.parse_args(
            [
                "all",
                "on",
                "--verbose",
                "--jsonl-path",
                "C:\\logs\\switchbot-ble.jsonl",
            ]
        )

        self.assertTrue(args.verbose)
        self.assertEqual(args.jsonl_path, "C:\\logs\\switchbot-ble.jsonl")

    def test_parser_accepts_excluded_addresses_for_all_mode(self) -> None:
        parser = switchbot_ble.build_parser()

        args = parser.parse_args(
            [
                "all",
                "off",
                "--exclude-address",
                "F0:9E:9E:9E:E8:02",
                "--exclude-address",
                "AA:BB:CC:DD:EE:FF",
            ]
        )

        self.assertEqual(
            args.exclude_address,
            ["F0:9E:9E:9E:E8:02", "AA:BB:CC:DD:EE:FF"],
        )


if __name__ == "__main__":
    unittest.main()
