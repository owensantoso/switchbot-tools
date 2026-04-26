import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "switchbot_ble_daemon.py"
SPEC = importlib.util.spec_from_file_location("switchbot_ble_daemon", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
switchbot_ble_daemon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switchbot_ble_daemon)


class BleDaemonTests(unittest.TestCase):
    def test_parser_accepts_status_autostart(self) -> None:
        parser = switchbot_ble_daemon.build_parser()

        args = parser.parse_args(["status", "--autostart"])

        self.assertEqual(args.command, "status")
        self.assertTrue(args.autostart)

    def test_parser_accepts_all_command_options(self) -> None:
        parser = switchbot_ble_daemon.build_parser()

        args = parser.parse_args(
            [
                "all",
                "off",
                "--parallel",
                "6",
                "--autostart",
                "--exclude-address",
                "F0:9E:9E:9E:E8:02",
            ]
        )

        self.assertEqual(args.command, "all")
        self.assertEqual(args.action, "off")
        self.assertEqual(args.parallel, 6)
        self.assertTrue(args.autostart)
        self.assertEqual(args.exclude_address, ["F0:9E:9E:9E:E8:02"])

    def test_build_all_request_includes_action_and_options(self) -> None:
        parser = switchbot_ble_daemon.build_parser()
        args = parser.parse_args(
            [
                "all",
                "temp",
                "--value",
                "2700",
                "--brightness",
                "60",
                "--parallel",
                "6",
                "--exclude-address",
                "F0:9E:9E:9E:E8:02",
            ]
        )

        payload = switchbot_ble_daemon.build_all_request(args)

        self.assertEqual(payload["command"], "all")
        self.assertEqual(payload["action"], "temp")
        self.assertEqual(payload["value"], 2700)
        self.assertEqual(payload["brightness"], 60)
        self.assertEqual(payload["parallel"], 6)
        self.assertEqual(payload["exclude_addresses"], ["F0:9E:9E:9E:E8:02"])

    def test_build_all_request_uses_empty_exclude_list_by_default(self) -> None:
        parser = switchbot_ble_daemon.build_parser()
        args = parser.parse_args(["all", "off"])

        payload = switchbot_ble_daemon.build_all_request(args)

        self.assertEqual(payload["exclude_addresses"], [])


if __name__ == "__main__":
    unittest.main()
