# Command Ideas

Ideas for growing `switchbot-tools` without losing the simple terminal feel.

## Good Next Commands

These are close to the current architecture:

```sh
switchbot-tools scenes find movie
switchbot-tools lights notify success
switchbot-tools lights pulse --color red --times 3
switchbot-tools lights fade warm-white --seconds 10
switchbot-tools devices --json
switchbot-tools doctor --cloud
switchbot-tools doctor --ble
switchbot-tools completion zsh
```

## Local Convenience Layer

These need local config, but would make the CLI feel much nicer:

```sh
switchbot-tools alias set desk "Office Desk Bulb"
switchbot-tools group create office "Desk lamp" "Monitor strip"
switchbot-tools group office brightness 35
switchbot-tools vibe focus
switchbot-tools vibe movie
```

## Automation

These probably need scheduling, state, or a long-running process:

```sh
switchbot-tools after 10m lights off
switchbot-tools bedtime --delay 20m
switchbot-tools schedule add "weekday 07:00" scenes run "Morning"
switchbot-tools watch "Bedroom Meter" --above 28 --then scenes run "Cool Down"
```

## Wider Device Support

These depend on SwitchBot device command coverage:

```sh
switchbot-tools bot "Coffee Button" press
switchbot-tools curtain "Bedroom" open
switchbot-tools curtain "Bedroom" close
switchbot-tools plug "Heater" toggle
switchbot-tools sensor "Bedroom Meter"
switchbot-tools sensors
```

## Scripting And Safety

These would make public use smoother:

```sh
switchbot-tools lights status --json
switchbot-tools lights off --dry-run
switchbot-tools wait "Desk lamp" --state off --timeout 30s
switchbot-tools raw GET /devices
switchbot-tools config show --redact
```

The main design rule: keep friendly commands obvious, keep raw/API commands explicit, and make dangerous operations easy to inspect before running.
