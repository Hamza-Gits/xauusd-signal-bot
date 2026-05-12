"""Load and validate MT5 configuration."""
import os
import sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"[FATAL] Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value

# AquaFunded MT5 credentials
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "646172"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "Cqx@L3p2HI")
MT5_SERVER   = os.getenv("MT5_SERVER", "AquaFunded-Server")

# Telegram
TELEGRAM_API_ID         = int(_require("TELEGRAM_API_ID"))
TELEGRAM_API_HASH       = _require("TELEGRAM_API_HASH")
TELEGRAM_PHONE          = _require("TELEGRAM_PHONE")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

_raw_groups = _require("TELEGRAM_GROUP_IDS")
TELEGRAM_GROUP_IDS = [g.strip() for g in _raw_groups.split(",") if g.strip()]

# Risk
RISK_PCT      = float(os.getenv("MT5_RISK_PCT", "0.01"))  # 1% = $50 on $5k
SYMBOL        = "XAUUSD"
MIN_LOT       = 0.01
LOT_PRECISION = 2

# Notifications
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "").strip()
