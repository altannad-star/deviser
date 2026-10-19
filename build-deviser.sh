#!/usr/bin/env bash
# build-deviser.sh — builds the Deviser AppImage on your Bazzite machine.
# Run:  bash build-deviser.sh
# Needs: internet + ~1GB disk, takes ~5 minutes.
set -e
echo "== Deviser 1.0 builder =="
mkdir -p deviser-build && cd deviser-build

echo "== 1/5 python deps =="
pip install --user pyinstaller zstandard olefile >/dev/null 2>&1 || pip install pyinstaller zstandard olefile

echo "== 2/5 unpacking sources =="
if [ ! -f ../deviser-final.tar.gz ]; then
  echo "ERROR: put deviser-final.tar.gz next to this script"; exit 1
fi
mkdir -p app
tar xzf ../deviser-final.tar.gz -C app
cp app/tools/iptinfo app/tools/ipt2obj app/tools/ipt2step app/build/deviser_app.py .

echo "== 3/5 freezing with PyInstaller =="
python3 -m PyInstaller --onefile --name Deviser \
  --add-data "iptinfo:." --add-data "ipt2obj:." --add-data "ipt2step:." \
  --hidden-import uuid --hidden-import re --hidden-import struct \
  --hidden-import datetime --hidden-import argparse --hidden-import json \
  --hidden-import webbrowser --hidden-import threading \
  --collect-all zstandard --collect-all olefile \
  deviser_app.py >/dev/null

echo "== 4/5 fetching appimagetool =="
python3 -c "import urllib.request; urllib.request.urlretrieve('https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage', 'appimagetool')"
chmod +x appimagetool

echo "== 5/5 building AppImage =="
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/256x256/apps
cp dist/Deviser AppDir/usr/bin/deviser
if [ -f app/tools/deviser.png ]; then
  cp app/tools/deviser.png AppDir/usr/share/icons/hicolor/256x256/apps/deviser.png
  cp app/tools/deviser.png AppDir/deviser.png
fi
cat > AppDir/AppRun << 'EOF2'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/deviser" "$@"
EOF2
chmod +x AppDir/AppRun
cat > AppDir/deviser.desktop << 'EOF2'
[Desktop Entry]
Type=Application
Name=Deviser
Comment=Clean-room Inventor .ipt viewer/exporter
Exec=deviser
Icon=deviser
Terminal=false
Categories=Engineering;Graphics;
EOF2
cp AppDir/deviser.desktop AppDir/usr/share/applications/
./appimagetool AppDir Deviser-1.0-x86_64.AppImage 2>/dev/null || ./appimagetool --appimage-extract-and-run AppDir Deviser-1.0-x86_64.AppImage
chmod +x Deviser-1.0-x86_64.AppImage
echo ""
echo "========================================================"
echo " DONE:  ./deviser-build/Deviser-1.0-x86_64.AppImage"
echo " Double-click it, or run:  ./deviser-build/Deviser-1.0-x86_64.AppImage &"
echo " Optional (enables in-app STEP export):"
echo "   pip install --user cadquery"
echo "========================================================"
