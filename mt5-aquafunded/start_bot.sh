#!/bin/bash
# ============================================================
# Start the MT5 signal bot on Oracle Cloud (run after setup).
# Use 'screen' so it keeps running after you close SSH.
# ============================================================

BOT_DIR="$HOME/xauusd-signal-bot/mt5-aquafunded"
LOG="$HOME/mt5_bot.log"

echo "Pulling latest code..."
cd "$HOME/xauusd-signal-bot" && git pull

echo "Starting virtual display..."
pkill Xvfb 2>/dev/null; sleep 1
Xvfb :99 -screen 0 1024x768x16 &
sleep 2

echo "Starting MT5 terminal (headless)..."
DISPLAY=:99 WINEPREFIX=~/.mt5 wine \
    ~/.mt5/drive_c/Program\ Files/MetaTrader\ 5/terminal64.exe /portable &
sleep 8  # Give MT5 time to connect

echo "Starting mt5linux bridge (Wine Python <-> Linux Python)..."
DISPLAY=:99 WINEPREFIX=~/.mt5 wine \
    "C:\\Python311\\python.exe" -m mt5linux 18812 &
sleep 3

echo "Starting signal bot..."
cd "$BOT_DIR"

# Create .env if it doesn't exist yet
if [ ! -f .env ]; then
    echo "ERROR: No .env file found in $BOT_DIR"
    echo "Create one using .env.mt5.template as a guide"
    exit 1
fi

# Run bot inside a screen session so it survives SSH disconnect
screen -dmS mt5bot python3 main_mt5.py
echo ""
echo "Bot is running in a screen session called 'mt5bot'"
echo ""
echo "Useful commands:"
echo "  screen -r mt5bot        # View live logs"
echo "  Ctrl+A then D           # Detach from logs (bot keeps running)"
echo "  screen -X -S mt5bot quit # Stop the bot"
echo "  tail -f $LOG            # View log file"
