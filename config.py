"""Load and validate configuration from environment variables."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"[FATAL] Required environment variable missing: {name}", file=sys.stderr)
        sys.exit(1)
    return value


# OANDA
OANDA_API_KEY = _require("OANDA_API_KEY")
OANDA_ACCOUNT_ID = _require("OANDA_ACCOUNT_ID")
OANDA_ENV = os.getenv("OANDA_ENV", "live").lower().strip()
if OANDA_ENV not in ("live", "practice"):
    print(f"[FATAL] OANDA_ENV must be 'live' or 'practice', got: {OANDA_ENV}", file=sys.stderr)
    sys.exit(1)

# Telegram
TELEGRAM_API_ID = int(_require("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = _require("TELEGRAM_API_HASH")
TELEGRAM_PHONE = _require("TELEGRAM_PHONE")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

_raw_groups = _require("TELEGRAM_GROUP_IDS")
TELEGRAM_GROUP_IDS = [g.strip() for g in _raw_groups.split(",") if g.strip()]

# Risk
RISK_PCT = float(os.getenv("RISK_PCT", "0.035"))
FORCE_MIN_UNITS = os.getenv("FORCE_MIN_UNITS", "true").lower() == "true"

# Entry chase — when a BUY signal arrives but ASK is already above signal entry
# (price moved up before we could place the LIMIT), market-in at current price
# IF we're still within MAX_ENTRY_CHASE_USD of the original entry. Beyond that,
# skip the signal: R:R has decayed too much and SL distance is too wide.
# Set to 0 to disable chasing entirely (pure LIMIT behaviour).
MAX_ENTRY_CHASE_USD = float(os.getenv("MAX_ENTRY_CHASE_USD", "2.0"))
# Don't keep a TP leg if it's within MIN_TP_DISTANCE_USD of the effective entry
# (would close almost immediately for ~zero profit, wasting the leg).
MIN_TP_DISTANCE_USD = float(os.getenv("MIN_TP_DISTANCE_USD", "0.8"))

# Notifications
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "").strip()

# Instrument
INSTRUMENT = "XAU_USD"
ACCOUNT_CURRENCY = "GBP"
