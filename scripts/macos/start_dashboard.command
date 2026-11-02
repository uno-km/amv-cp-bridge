#!/bin/bash
# Double-click this file in Finder to launch amv-cp-bridge dashboard
if [ -x "$HOME/.amv_cp_bridge/venv/bin/python" ]; then
  exec "$HOME/.amv_cp_bridge/venv/bin/python" -m amv_cp_bridge.cli dashboard --port 11500
fi
cd "$(dirname "$0")/../.."
python3 -m amv_cp_bridge.cli dashboard --port 11500
