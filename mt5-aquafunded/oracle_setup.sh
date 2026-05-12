#!/bin/bash
# ============================================================
# Oracle Cloud Ubuntu setup for AquaFunded MT5 Signal Bot
# Run this ONCE after SSH-ing into your Oracle VM:
#   bash oracle_setup.sh
# ============================================================
set -e

echo "=== Step 1: System update ==="
sudo apt update && sudo apt upgrade -y

echo "=== Step 2: Install core tools ==="
sudo apt install -y wget curl git screen python3 python3-pip xvfb x11-utils

echo "=== Step 3: Install Wine (Windows compatibility) ==="
sudo dpkg --add-architecture i386
sudo mkdir -pm755 /etc/apt/keyrings
sudo wget -O /etc/apt/keyrings/winehq-archive.key \
    https://dl.winehq.org/wine-builds/winehq.key
sudo wget -NP /etc/apt/sources.list.d/ \
    https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources
sudo apt update
sudo apt install -y --install-recommends winehq-stable

echo "=== Step 4: Init Wine prefix (64-bit) ==="
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x16 &
sleep 2
WINEARCH=win64 WINEPREFIX=~/.mt5 wineboot --init
sleep 3

echo "=== Step 5: Install Windows Python 3.11 inside Wine ==="
wget -q -O /tmp/python-win.exe \
    "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
DISPLAY=:99 WINEPREFIX=~/.mt5 wine /tmp/python-win.exe \
    /quiet InstallAllUsers=1 PrependPath=1
sleep 5

echo "=== Step 6: Install MetaTrader5 + mt5linux in Wine Python ==="
WINEPREFIX=~/.mt5 wine \
    "C:\\Python311\\python.exe" -m pip install MetaTrader5 mt5linux

echo "=== Step 7: Download MT5 terminal ==="
wget -q -O /tmp/mt5setup.exe \
    "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
echo "Installing MT5 — this opens a window, click through or wait for auto-install..."
DISPLAY=:99 WINEPREFIX=~/.mt5 wine /tmp/mt5setup.exe /auto
sleep 10

echo "=== Step 8: Install Python dependencies (Linux side) ==="
pip3 install --user mt5linux telethon python-dotenv truststore

echo "=== Step 9: Clone/update the bot repo ==="
if [ ! -d ~/xauusd-signal-bot ]; then
    git clone https://github.com/Hamza-Gits/xauusd-signal-bot.git ~/xauusd-signal-bot
else
    cd ~/xauusd-signal-bot && git pull
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo ""
echo "NEXT STEPS:"
echo "1. Start MT5 and log in manually (first time only):"
echo "   bash ~/xauusd-signal-bot/mt5-aquafunded/start_mt5_gui.sh"
echo ""
echo "2. Then run the bot:"
echo "   bash ~/xauusd-signal-bot/mt5-aquafunded/start_bot.sh"
echo "=========================================="
