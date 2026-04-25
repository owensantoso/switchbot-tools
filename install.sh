#!/bin/sh
set -eu

REPO_URL="${SWITCHBOT_TOOLS_REPO_URL:-https://github.com/owensantoso/switchbot-tools.git}"
INSTALL_ROOT="${SWITCHBOT_TOOLS_INSTALL_ROOT:-$HOME/.local/share/switchbot-tools}"
BIN_DIR="${SWITCHBOT_TOOLS_BIN_DIR:-$HOME/.local/bin}"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

if ! command_exists git; then
  echo "git is required to install switchbot-tools." >&2
  exit 1
fi

if ! command_exists python3; then
  echo "python3 is required to install switchbot-tools." >&2
  exit 1
fi

mkdir -p "$BIN_DIR" "$(dirname "$INSTALL_ROOT")"

if [ -d "$INSTALL_ROOT/.git" ]; then
  git -C "$INSTALL_ROOT" pull --ff-only
else
  rm -rf "$INSTALL_ROOT"
  git clone "$REPO_URL" "$INSTALL_ROOT"
fi

python3 -m venv "$INSTALL_ROOT/.venv"
"$INSTALL_ROOT/.venv/bin/pip" install --upgrade pip
"$INSTALL_ROOT/.venv/bin/pip" install -r "$INSTALL_ROOT/requirements.txt"

ln -sf "$INSTALL_ROOT/bin/switchbot-tools" "$BIN_DIR/switchbot-tools"
ln -sf "$INSTALL_ROOT/bin/sblights" "$BIN_DIR/sblights"

echo "Installed switchbot-tools to $INSTALL_ROOT"
echo "Commands linked in $BIN_DIR"
echo "Add this to your shell profile if needed:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
