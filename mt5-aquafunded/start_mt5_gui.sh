#!/bin/bash
# ============================================================
# First-time only: start MT5 with a visible window via VNC
# so you can log in to AquaFunded manually.
# After logging in once, MT5 saves credentials automatically.
# ============================================================

echo "Starting virtual display..."
pkill Xvfb 2>/dev/null; sleep 1
Xvfb :99 -screen 0 1280x800x24 &
sleep 2

echo "Installing VNC so you can see the MT5 window..."
sudo apt install -y x11vnc 2>/dev/null

echo "Starting VNC on port 5900 (no password for simplicity)..."
x11vnc -display :99 -nopw -listen 0.0.0.0 -xkb &

echo ""
echo "=== Connect via VNC ==="
echo "From your PC, download a VNC viewer (e.g. RealVNC or TigerVNC)"
echo "Connect to: <your-oracle-ip>:5900"
echo ""
echo "Starting MT5..."
DISPLAY=:99 WINEPREFIX=~/.mt5 wine \
    ~/.mt5/drive_c/Program\ Files/MetaTrader\ 5/terminal64.exe &

echo ""
echo "MT5 is starting. Connect via VNC to:"
echo "  1. Enter server: AquaFunded-Server"
echo "  2. Login: 646172"
echo "  3. Password: Cqx@L3p2HI"
echo "  4. Click OK — MT5 will connect and save credentials"
echo ""
echo "Once logged in, press Ctrl+C here and run start_bot.sh"
wait
