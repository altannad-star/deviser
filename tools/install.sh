#!/usr/bin/env bash
# Deviser tools installer for Bazzite KDE (and any Linux).
# Installs iptinfo + ipt2obj to ~/.local/bin and a Dolphin service menu.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
MENU_DIR="$HOME/.local/share/kio/servicemenus"
mkdir -p "$BIN_DIR" "$MENU_DIR"
install -m 755 "$SCRIPT_DIR/iptinfo"  "$BIN_DIR/iptinfo"
install -m 755 "$SCRIPT_DIR/ipt2obj"  "$BIN_DIR/ipt2obj"
install -m 755 "$SCRIPT_DIR/verify.sh" "$BIN_DIR/iptinfo-verify"
cat > "$MENU_DIR/deviser.desktop" << 'DESKTOP'
[Desktop Entry]
Type=Service
MimeType=application/x-ipt;
Actions=iptInfo;iptThumb;iptObj;

[Desktop Action iptInfo]
Name=Show Inventor part info
Icon=dialog-information
Exec=konsole --hold -e iptinfo %f

[Desktop Action iptThumb]
Name=Extract thumbnail (PNG)
Icon=image-x-generic
Exec=konsole --hold -e iptinfo --thumbnail %f %f

[Desktop Action iptObj]
Name=Export to 3D mesh (OBJ)
Icon=application-octet-stream
Exec=konsole --hold -e ipt2obj %f
DESKTOP
echo "installed:"
echo "  $BIN_DIR/iptinfo, ipt2obj, iptinfo-verify"
echo "  $MENU_DIR/deviser.desktop (Dolphin menu: info / thumbnail / export OBJ)"
echo ""
echo "Dependencies: pip install --user olefile zstandard"
echo "Then run: kbuildsycoca6 --noincremental  (or log out/in)"
echo "Verify with: iptinfo-verify YOURPART.ipt"
