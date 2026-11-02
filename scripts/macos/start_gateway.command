#!/bin/bash
# Double-click this file in Finder to launch amv-cp-bridge gateway only
cd "$HOME/.amv_cp_bridge/app" 2>/dev/null || cd "$(dirname "$0")/../.."
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
python3 -m amv_cp_bridge.cli gateway --port 11500
