import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "switchbot_ble.py"
SPEC = importlib.util.spec_from_file_location("switchbot_ble", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
switchbot_ble = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switchbot_ble)


class FakeLight:
    def __init__(self) -> None:
        self._turn_on_command = "570101"
        self._turn_off_command = "570102"
        self._set_brightness_command = "5702{}"
        self._set_color_temp_command = "5703{}"
        self._set_rgb_command = "5704{}"
        self.sent_commands: list[str] = []
        self.turn_on_called = False

    def _check_function_support(self, command: str) -> None:
        if not command:
            raise AssertionError("missing command")

    @staticmethod
    def _validate_brightness(value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError("bad brightness")

    @staticmethod
    def _validate_color_temp(value: int) -> None:
        if not 2700 <= value <= 6500:
            raise ValueError("bad color temp")

    @staticmethod
    def _validate_rgb(r: int, g: int, b: int) -> None:
        for value in (r, g, b):
            if not 0 <= value <= 255:
                raise ValueError("bad rgb")

    async def _send_command(self, command: str) -> bytes:
        self.sent_commands.append(command)
        return bytes([1])

    @staticmethod
    def _check_command_result(result: bytes, _index: int, _values: set[int]) -> bool:
        return result == bytes([1])

    async def turn_on(self) -> bool:
        self.turn_on_called = True
        return True


class FastModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_action_path_skips_decorated_library_method(self) -> None:
        device = FakeLight()
        args = SimpleNamespace(action="on", value=None, brightness=100, r=255, g=255, b=255)

        result = await switchbot_ble.perform_action_fast(device, args)

        self.assertTrue(result)
        self.assertEqual(device.sent_commands, ["570101"])
        self.assertFalse(device.turn_on_called)

    async def test_fast_temp_command_formats_brightness_and_kelvin(self) -> None:
        device = FakeLight()
        args = SimpleNamespace(action="temp", value=2700, brightness=60, r=255, g=255, b=255)

        result = await switchbot_ble.perform_action_fast(device, args)

        self.assertTrue(result)
        self.assertEqual(device.sent_commands, ["57033C0A8C"])


if __name__ == "__main__":
    unittest.main()
