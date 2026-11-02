# amv-cp-bridge Safari Extension

Safari Web Extension for macOS.

## Build (requires macOS + Xcode)

```bash
# 1. Convert Chrome extension to Safari format
xcrun safari-web-extension-converter ../extension \
  --project-location ./xcode-project \
  --app-name "amv-cp-bridge" \
  --bundle-identifier com.ameva.amv-cp-bridge

# 2. Open in Xcode and build
open ./xcode-project/amv-cp-bridge.xcodeproj

# 3. Or from command line
cd ./xcode-project
xcodebuild -scheme "amv-cp-bridge" -configuration Release
```

## How it works

Safari Web Extensions use the same Manifest V3 format as Chrome.
The `safari-web-extension-converter` tool wraps the Chrome extension
in a native macOS app container that Safari can load.

## Manual install (Development)

1. Build the Xcode project
2. Enable "Allow unsigned extensions" in Safari > Develop menu
3. Enable the extension in Safari > Settings > Extensions
