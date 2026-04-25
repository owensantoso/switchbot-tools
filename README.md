# switchbot-tools

Unofficial command-line tools for controlling SwitchBot devices from the terminal.

The primary surface is fast whole-room light control. The repo also includes scene execution, device commands, setup diagnostics, raw API access, and optional local BLE control for nearby bulbs and light strips.

## Contents

- [Install](#install)
- [Credentials](#credentials)
- [Quick Start](#quick-start)
- [Command Reference](#command-reference)
- [Bluetooth Mode](#bluetooth-mode)
- [Troubleshooting](#troubleshooting)
- [Roadmap Ideas](#roadmap-ideas)

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

```sh
git clone https://github.com/owensantoso/switchbot-tools.git
cd switchbot-tools
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ln -sf "$PWD/bin/switchbot-tools" "$HOME/.local/bin/switchbot-tools"
ln -sf "$PWD/bin/sblights" "$HOME/.local/bin/sblights"
```

## Credentials

Cloud API commands read credentials from `~/.switchbot.env`.

Create a starter file:

```sh
switchbot-tools config init
```

Then edit it:

```sh
export SWITCHBOT_TOKEN="your-token"
export SWITCHBOT_SECRET="your-secret"
```

One-click reference: [SwitchBot: How to Obtain a Token?](https://support.switch-bot.com/hc/en-us/articles/12822710195351-How-to-Obtain-a-Token)

In the SwitchBot app:

1. Open `Profile`.
2. Go to `Preferences`.
3. Open `About` or `App Version`.
4. Tap the app version repeatedly, usually 5-15 times, until `Developer Options` appears.
5. Open `Developer Options`.
6. Copy the token and secret key into `~/.switchbot.env`.

Do not commit `~/.switchbot.env` or paste those values into logs.

## Quick Start

```sh
switchbot-tools doctor
switchbot-tools devices
switchbot-tools scenes list
switchbot-tools lights warm-white --brightness 60
switchbot-tools lights toggle
switchbot-tools device "Desk lamp" brightness 35
switchbot-tools scenes run "Movie mode"
```

The old light shortcut still works:

```sh
sblights purple
sblights off
sblights toggle
```

`sblights <action>` is equivalent to `switchbot-tools lights <action>`.

## Command Reference

### Setup

```sh
switchbot-tools doctor
switchbot-tools config path
switchbot-tools config sample
switchbot-tools config init
switchbot-tools version
```

### Devices

```sh
switchbot-tools devices
switchbot-tools devices list
switchbot-tools status "Desk lamp"
switchbot-tools device "Desk lamp" status
switchbot-tools device "Desk lamp" on
switchbot-tools device "Desk lamp" off
switchbot-tools device "Desk lamp" toggle
switchbot-tools device "Desk lamp" brightness 35
switchbot-tools device "Desk lamp" temp 2700
switchbot-tools device "Desk lamp" color 255 120 0
```

Device commands accept a device ID, exact device name, or unambiguous partial name.

### Scenes

```sh
switchbot-tools scenes list
switchbot-tools scenes run "Movie mode"
switchbot-tools scene "Movie mode"
switchbot-tools scene list
switchbot-tools dim
```

`dim` is a convenience alias for a scene named `Dim lights`.

### Lights

```sh
switchbot-tools lights on
switchbot-tools lights off
switchbot-tools lights resume
switchbot-tools lights toggle
switchbot-tools lights status
```

Presets:

```sh
switchbot-tools lights purple
switchbot-tools lights gold
switchbot-tools lights red
switchbot-tools lights green
switchbot-tools lights blue
switchbot-tools lights pink
switchbot-tools lights orange
switchbot-tools lights cyan
switchbot-tools lights warm-white
switchbot-tools lights cool-white
switchbot-tools lights daylight
```

Direct values:

```sh
switchbot-tools lights rgb 255 120 0
switchbot-tools lights temp 2700
switchbot-tools lights brightness 40
switchbot-tools lights cool-white --max
switchbot-tools lights warm-white --brightness 60
```

### Raw API Helper

For lower-level commands, pass arguments directly to the bundled Python cloud CLI:

```sh
switchbot-tools raw devices
switchbot-tools raw scenes
switchbot-tools raw status DEVICE_ID
switchbot-tools raw brightness DEVICE_ID 35
```

## Bluetooth Mode

BLE mode talks directly to nearby SwitchBot bulbs and light strips using `PySwitchbot`.

Scan first:

```sh
switchbot-tools lights --ble scan --timeout 5
```

Then run commands from the cached BLE device list:

```sh
switchbot-tools lights --ble warm-white
switchbot-tools lights --ble rgb 255 120 0
switchbot-tools lights --ble brightness 70
switchbot-tools lights --ble off
```

Use `--discover` to refresh nearby devices before a command:

```sh
switchbot-tools lights --ble --discover gold
```

Cloud-only commands include scenes, `toggle`, and status checks.

## Troubleshooting

Start with:

```sh
switchbot-tools doctor
```

Common checks:

- `Missing SwitchBot credentials`: create or update `~/.switchbot.env`.
- `No device found matching`: run `switchbot-tools devices` and use a more specific name or device ID.
- BLE commands cannot find lights: run `switchbot-tools lights --ble scan --timeout 5`, then retry.
- BLE package missing: reinstall with the quick install command or run `pip install -r requirements.txt` in the repo venv.

## Roadmap Ideas

Ideas that came up while shaping the public command surface:

- `lights fade`, `lights pulse`, `lights notify success|fail|warn`
- `scene find`, `scene chain`
- local nicknames, groups, and room-style aliases
- `after 10m lights off` sleep timers
- sensor summaries for temperature, humidity, motion, and contact devices
- cloud/BLE fallback mode with `--transport cloud|ble|auto`
- shell completions for zsh, bash, and fish
- `--json`, `--quiet`, and `--dry-run` for scripting

See [docs/command-ideas.md](docs/command-ideas.md) for the longer brainstorm.

The core rule for future commands: keep `switchbot-tools lights ...` friendly, keep raw/API access explicit, and make anything dangerous easy to inspect before running.

## Disclaimer

This project is unofficial and not affiliated with SwitchBot or WonderLabs.
