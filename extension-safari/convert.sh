#!/bin/bash
# Convert Chrome extension to Safari Web Extension
# Run on macOS with Xcode installed
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHROME_EXT="$SCRIPT_DIR/../extension"
OUTPUT="$SCRIPT_DIR/xcode-project"

if ! command -v xcrun &>/dev/null; then
  echo "[!] Xcode command line tools required."
  echo "    Install: xcode-select --install"
  exit 1
fi

echo "[*] Converting Chrome extension to Safari Web Extension..."
xcrun safari-web-extension-converter "$CHROME_EXT" \
  --project-location "$OUTPUT" \
  --app-name "amv-cp-bridge" \
  --bundle-identifier com.ameva.amv-cp-bridge \
  --no-open \
  --force

echo "[+] Xcode project created at: $OUTPUT"
echo "    Open with: open $OUTPUT/amv-cp-bridge.xcodeproj"
