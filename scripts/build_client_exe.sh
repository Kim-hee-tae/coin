#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/build_client_exe.sh
# Optional:
#   CLIENT_NAME=AirBattleClient ./scripts/build_client_exe.sh

CLIENT_NAME="${CLIENT_NAME:-AirBattleClient}"

python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller \
  --onefile \
  --name "$CLIENT_NAME" \
  client.py

echo "[DONE] Executable generated at: dist/$CLIENT_NAME"
