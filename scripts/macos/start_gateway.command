#!/bin/bash
# Double-click this file in Finder to launch amv-cp-bridge gateway only
if [ -x "$HOME/.amv_cp_bridge/venv/bin/python" ]; then
  exec "$HOME/.amv_cp_bridge/venv/bin/python" -m amv_cp_bridge.cli gateway --port 11500
fi
cd "$(dirname "$0")/../.."
python3 -m amv_cp_bridge.cli gateway --port 11500
