#!/bin/sh
# Build "Bot Monitoring Room.app", a menu-bar companion for macOS 13+ (needs the Xcode command line tools).
#   ./packaging/macos/build-app.sh            # → dist/Bot Monitoring Room.app
# Then drag it into /Applications, open it, and tick "Start at login" in its menu.
set -e
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"
OUT="${1:-$REPO/dist}"
APP="$OUT/Bot Monitoring Room.app"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml")"

command -v swiftc >/dev/null 2>&1 || { echo "swiftc not found. Run: xcode-select --install"; exit 1; }
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -target "$(uname -m)-apple-macos13.0" -o "$APP/Contents/MacOS/BotMonitor" BotMonitorMenu.swift \
  -framework Cocoa -framework ServiceManagement

# Escape the checkout path for XML before writing it into Info.plist.
REPO_XML="$(printf '%s' "$REPO" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g')"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Bot Monitoring Room</string>
  <key>CFBundleDisplayName</key><string>Bot Monitoring Room</string>
  <key>CFBundleIdentifier</key><string>io.github.olivia295.botoffice</string>
  <key>CFBundleExecutable</key><string>BotMonitor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION:-0.0.0}</string>
  <key>CFBundleVersion</key><string>${VERSION:-0.0.0}</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>BotMonitorRepo</key><string>${REPO_XML}</string>
</dict>
</plist>
PLIST

# App icon from docs/logo.svg, when Quick Look can render it.
TMP="$(mktemp -d)"
if qlmanage -t -s 1024 -o "$TMP" "$REPO/docs/logo.svg" >/dev/null 2>&1 && [ -f "$TMP/logo.svg.png" ]; then
  mkdir -p "$TMP/AppIcon.iconset"
  for size in 16 32 128 256 512; do
    sips -z $size $size "$TMP/logo.svg.png" --out "$TMP/AppIcon.iconset/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$TMP/logo.svg.png" --out "$TMP/AppIcon.iconset/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns" || true
fi
rm -rf "$TMP"

codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"
echo "Drag it into /Applications and open it; tick \"Start at login\" in its menu to keep it running."
