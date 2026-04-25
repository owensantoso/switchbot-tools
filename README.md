# switchbot-tools

Unofficial command-line tools for controlling SwitchBot devices from the terminal.

The current focus is fast whole-room light control, SwitchBot scenes, and optional local Bluetooth control for nearby bulbs and light strips.

## Features

- Friendly light presets: `purple`, `gold`, `warm-white`, `cool-white`, `daylight`, and more.
- Whole-room commands for all SwitchBot color bulbs and light strips with cloud service enabled.
- Scene execution by name.
- `toggle` that reads current cloud state first, then turns all lights on or off by majority state.
- Optional direct BLE mode for local bulb/strip control.
- `sblights` compatibility alias for older local scripts.

## Install

### Quick Install

macOS and Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/owensantoso/switchbot-tools/main/install.sh | bash
```

This installs the commands to `~/.local/bin` and creates a private Python environment in `~/.local/share/switchbot-tools`.

Make sure `~/.local/bin` is on your `PATH`:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

### Manual Install

Clone the repo, create a Python environment, and install dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then add `bin` to your `PATH`, or symlink the commands somewhere already on your `PATH`:

```sh
ln -sf "$PWD/bin/switchbot-tools" "$HOME/.local/bin/switchbot-tools"
ln -sf "$PWD/bin/sblights" "$HOME/.local/bin/sblights"
```

## Credentials

For cloud API commands, create `~/.switchbot.env`:

```sh
export SWITCHBOT_TOKEN="your-token"
export SWITCHBOT_SECRET="your-secret"
```

You can get these from the SwitchBot app developer settings. Do not commit this file.

One-click reference: [SwitchBot: How to Obtain a Token?](https://support.switch-bot.com/hc/en-us/articles/12822710195351-How-to-Obtain-a-Token)

In the SwitchBot app:

1. Open `Profile`.
2. Go to `Preferences`.
3. Open `About` or `App Version`.
4. Tap the app version repeatedly, usually 5-15 times, until `Developer Options` appears.
5. Open `Developer Options`.
6. Copy the token and secret key into `~/.switchbot.env`.

## Usage

```sh
switchbot-tools lights purple
switchbot-tools lights warm-white --brightness 60
switchbot-tools lights cool-white --max
switchbot-tools lights off
switchbot-tools lights toggle
switchbot-tools dim
switchbot-tools scene "Movie mode"
switchbot-tools devices
```

The compatibility alias keeps older automations working:

```sh
sblights purple
sblights off
sblights toggle
```

## Bluetooth Mode

BLE mode talks directly to nearby SwitchBot bulbs and light strips using `python-switchbot`.

Scan first:

```sh
switchbot-tools lights --ble scan --timeout 5
```

Then run commands from the cached BLE device list:

```sh
switchbot-tools lights --ble warm-white
switchbot-tools lights --ble purple --brightness 70
switchbot-tools lights --ble off
```

Use `--discover` to refresh nearby devices before a command:

```sh
switchbot-tools lights --ble --discover gold
```

## Raw API Helper

For lower-level commands, pass arguments directly to the bundled Python cloud CLI:

```sh
switchbot-tools raw scenes
switchbot-tools raw status DEVICE_ID
switchbot-tools raw brightness DEVICE_ID 35
```

## Status

This is an early personal-tool-turned-public repo. The cloud API path is the most complete. BLE support is useful but depends on nearby device discovery, macOS/Bluetooth behavior, and the `python-switchbot` package.

## Disclaimer

This project is unofficial and not affiliated with SwitchBot or WonderLabs.
