#!/bin/bash
# amv-cp-bridge macOS Installer
# Usage: curl -fsSL <url>/install.sh | bash
set -e

echo "======================================"
echo " amv-cp-bridge Installer (macOS)"
echo "======================================"

# 1. Check Python 3.10+
if ! command -v python3 &>/dev/null; then
  echo "[!] Python3 not found. Install via: brew install python@3.12"
  exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[+] Python $PY_VER detected"

# 2. Check Microsoft Edge
EDGE_APP="/Applications/Microsoft Edge.app"
if [ ! -d "$EDGE_APP" ]; then
  echo "[!] Microsoft Edge not found."
  echo "    Install from: https://www.microsoft.com/edge"
  echo "    Or via brew: brew install --cask microsoft-edge"
  exit 1
fi
echo "[+] Microsoft Edge detected"

# 3. Clone or update
INSTALL_DIR="$HOME/.amv_cp_bridge/app"
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "[*] Updating existing installation..."
  cd "$INSTALL_DIR"
  git pull --ff-only
else
  echo "[*] Installing amv-cp-bridge..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone https://github.com/uno-km/amv-cp-bridge.git "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# 4. Create venv and install dependencies
echo "[*] Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
playwright install chromium

# 5. Create launch script
LAUNCH="$HOME/.amv_cp_bridge/start.sh"
cat > "$LAUNCH" << 'SCRIPT'
#!/bin/bash
cd "$HOME/.amv_cp_bridge/app"
source .venv/bin/activate
python -m amv_cp_bridge.cli dashboard --port 11500
SCRIPT
chmod +x "$LAUNCH"

# 6. Create accounts config template
ACCOUNTS="$HOME/.amv_cp_bridge/accounts.json"
if [ ! -f "$ACCOUNTS" ]; then
  cat > "$ACCOUNTS" << JSON
[
  {
    "name": "account-1",
    "port": 9333,
    "profile_dir": "$HOME/.amv_cp_bridge/profiles/account1"
  }
]
JSON
  echo "[+] Created accounts config: $ACCOUNTS"
  echo "    Edit this file to add your M365 Copilot accounts."
fi

echo ""
echo "======================================"
echo " Installation complete!"
echo "======================================"
echo ""
echo " Start dashboard:  $LAUNCH"
echo " Or:  cd $INSTALL_DIR && source .venv/bin/activate && python -m amv_cp_bridge.cli dashboard"
echo ""
echo " Gateway API:      http://localhost:11500/v1/chat/completions"
echo " Dashboard:        http://localhost:11500/dashboard"
echo ""
echo " First time setup:"
echo "   1. Open Microsoft Edge and sign into M365 Copilot (https://m365.cloud.microsoft/chat)"
echo "   2. Edit $ACCOUNTS with your account details"
echo "   3. Run $LAUNCH"
echo ""
