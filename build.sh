#!/bin/bash
# Build Programmer Process Viewer: binary → .app bundle → polished .dmg installer.
# Artifacts land in dist/:
#   dist/Programmer Process Viewer.app
#   dist/Programmer Process Viewer.dmg
set -euo pipefail

cd "$(dirname "$0")"

PROJECT_DIR="$(pwd)"
VENV="$PROJECT_DIR/.venv"
VENV_PY="$VENV/bin/python"

APP_NAME="Programmer Process Viewer"
APP_BUNDLE="dist/${APP_NAME}.app"
DMG_NAME="${APP_NAME}.dmg"
DMG_VOLNAME="${APP_NAME}"
BIN_NAME="programmer_process_viewer"
ICON_SRC="$PROJECT_DIR/PPVIcon.png"
BG_1X="$PROJECT_DIR/packaging/background.png"
BG_2X="$PROJECT_DIR/packaging/background@2x.png"
BG_TIFF="$PROJECT_DIR/build/background.tiff"

STAGING="$PROJECT_DIR/build/dmg_staging"
ICONSET_TMP="$PROJECT_DIR/build/ProcessViewer.iconset"
ICNS_OUT="$PROJECT_DIR/build/ProcessViewer.icns"

if [ ! -d "$VENV" ]; then
    echo "error: venv not found at $VENV. Run:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pyinstaller Pillow" >&2
    exit 1
fi

echo "==> [1/6] Regenerating DMG background (1x + 2x → multi-res TIFF)"
"$VENV_PY" packaging/gen_background.py
mkdir -p "$(dirname "$BG_TIFF")"
rm -f "$BG_TIFF"
tiffutil -cathidpicheck "$BG_1X" "$BG_2X" -out "$BG_TIFF" >/dev/null

echo "==> [2/6] Building .icns from $ICON_SRC"
rm -rf "$ICONSET_TMP" "$ICNS_OUT"
mkdir -p "$ICONSET_TMP"
sips -z 16   16   "$ICON_SRC" --out "$ICONSET_TMP/icon_16x16.png"       >/dev/null
sips -z 32   32   "$ICON_SRC" --out "$ICONSET_TMP/icon_16x16@2x.png"    >/dev/null
sips -z 32   32   "$ICON_SRC" --out "$ICONSET_TMP/icon_32x32.png"       >/dev/null
sips -z 64   64   "$ICON_SRC" --out "$ICONSET_TMP/icon_32x32@2x.png"    >/dev/null
sips -z 128  128  "$ICON_SRC" --out "$ICONSET_TMP/icon_128x128.png"     >/dev/null
sips -z 256  256  "$ICON_SRC" --out "$ICONSET_TMP/icon_128x128@2x.png"  >/dev/null
sips -z 256  256  "$ICON_SRC" --out "$ICONSET_TMP/icon_256x256.png"     >/dev/null
sips -z 512  512  "$ICON_SRC" --out "$ICONSET_TMP/icon_256x256@2x.png"  >/dev/null
sips -z 512  512  "$ICON_SRC" --out "$ICONSET_TMP/icon_512x512.png"     >/dev/null
sips -z 1024 1024 "$ICON_SRC" --out "$ICONSET_TMP/icon_512x512@2x.png"  >/dev/null
iconutil -c icns "$ICONSET_TMP" -o "$ICNS_OUT"

echo "==> [3/6] Compiling standalone binary with PyInstaller"
rm -rf build/__pyinstaller dist/"$BIN_NAME" dist/"$BIN_NAME".app
"$VENV_PY" -m PyInstaller \
    --onefile \
    --name "$BIN_NAME" \
    --collect-all textual \
    --distpath dist \
    --workpath build/__pyinstaller \
    --specpath build/__pyinstaller \
    --noconfirm \
    process_viewer.py >/dev/null

echo "==> [4/6] Assembling $APP_BUNDLE"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"
cp "$ICNS_OUT" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
cp "dist/$BIN_NAME" "$APP_BUNDLE/Contents/Resources/$BIN_NAME"
chmod +x "$APP_BUNDLE/Contents/Resources/$BIN_NAME"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>local.processviewer.ppv</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

cat > "$APP_BUNDLE/Contents/MacOS/launcher" <<'LAUNCHER'
#!/bin/bash
# Opens Terminal.app and runs the bundled binary so the TUI has a real tty.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$SCRIPT_DIR/../Resources/programmer_process_viewer"
BIN_ESC="${BIN//\\/\\\\}"
BIN_ESC="${BIN_ESC//\"/\\\"}"
osascript <<EOF
tell application "Terminal"
    activate
    do script "clear && \"$BIN_ESC\"; exit"
end tell
EOF
LAUNCHER
chmod +x "$APP_BUNDLE/Contents/MacOS/launcher"

plutil -lint "$APP_BUNDLE/Contents/Info.plist" >/dev/null

echo "==> [5/6] Staging DMG contents"
rm -rf "$STAGING"
mkdir -p "$STAGING/.background"
cp "$BG_TIFF" "$STAGING/.background/background.tiff"
cp -R "$APP_BUNDLE" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
# Use the app icon as the volume icon (Finder requires a file named .VolumeIcon.icns).
cp "$ICNS_OUT" "$STAGING/.VolumeIcon.icns"
SetFile -c icnC "$STAGING/.VolumeIcon.icns" 2>/dev/null || true

echo "==> [6/6] Building DMG"
rm -f "dist/$DMG_NAME" build/rw.dmg

# Create a writable image from the staging folder, mount it, style it, unmount, then compress.
hdiutil create \
    -srcfolder "$STAGING" \
    -volname "$DMG_VOLNAME" \
    -fs HFS+ \
    -fsargs "-c c=64,a=16,e=16" \
    -format UDRW \
    -ov build/rw.dmg >/dev/null

MOUNT_OUTPUT=$(hdiutil attach -readwrite -noverify -noautoopen build/rw.dmg)
MOUNT_DEV=$(echo "$MOUNT_OUTPUT" | grep -E '^/dev/' | head -1 | awk '{print $1}')
MOUNT_POINT="/Volumes/$DMG_VOLNAME"

# Mark the volume as having a custom icon.
SetFile -a C "$MOUNT_POINT" 2>/dev/null || true

osascript <<APPLESCRIPT
tell application "Finder"
    tell disk "$DMG_VOLNAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 800, 520}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 128
        set text size of viewOptions to 13
        set background picture of viewOptions to file ".background:background.tiff"
        set position of item "${APP_NAME}.app" of container window to {150, 200}
        set position of item "Applications" of container window to {450, 200}
        close
        open
        update without registering applications
        delay 1
    end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$MOUNT_DEV" -quiet || hdiutil detach "$MOUNT_DEV" -force -quiet

hdiutil convert build/rw.dmg \
    -format UDZO \
    -imagekey zlib-level=9 \
    -o "dist/$DMG_NAME" >/dev/null

rm -f build/rw.dmg
rm -rf "$STAGING"

DMG_SIZE=$(du -h "dist/$DMG_NAME" | awk '{print $1}')
APP_SIZE=$(du -sh "$APP_BUNDLE" | awk '{print $1}')

echo
echo "  ✓ App:  $APP_BUNDLE   ($APP_SIZE)"
echo "  ✓ DMG:  dist/$DMG_NAME   ($DMG_SIZE)"
