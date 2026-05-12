"""Load and validate MT5/MetaAPI configuration."""
import os
import sys
from dotenv import load_dotenv

# Load from mt5-aquafunded/.env if it exists, else fall back to env vars
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"[FATAL] Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value

# MetaAPI (connects to AquaFunded MT5 server)
METAAPI_TOKEN      = _require("METAAPI_TOKEN")
METAAPI_ACCOUNT_ID = _require("METAAPI_ACCOUNT_ID")

# Telegram (same account, same groups as OANDA bot)
TELEGRAM_API_ID        = int(_require("TELEGRAM_API_ID"))
TELEGRAM_API_HASH      = _require("TELEGRAM_API_HASH")
TELEGRAM_PHONE         = _require("TELEGRAM_PHONE")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

_raw_groups = _require("TELEGRAM_GROUP_IDS")
TELEGRAM_GROUP_IDS = [g.strip() for g in _raw_groups.split(",") if g.strip()]

# Risk — 1% of $5k = $50 per trade
RISK_PCT       = float(os.getenv("MT5_RISK_PCT", "0.01"))
SYMBOL         = "XAUUSD"
MIN_LOT        = 0.01
LOT_PRECISION  = 2   # 0.01 lot steps

# Notifications
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "").strip()
