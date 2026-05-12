"""Trade journal for MT5 bot — logs orders and tracks WIN/LOSE outcomes."""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
JOURNAL_FILE = Path(__file__).parent / "trade_journal_mt5.json"


def load_journal() -> dict:
    if JOURNAL_FILE.exists():
        try:
            with open(JOURNAL_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"trades": []}


def save_journal(j: dict):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(j, f, indent=2)


def log_order(order_id, direction, entry, stop_loss, take_profit, lots):
    j = load_journal()
    j["trades"].append({
        "order_id": str(order_id),
        "placed_at": datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "lots": lots,
        "result": None,
    })
    save_journal(j)


def get_last_result() -> str:
    """Return 'WIN', 'LOSE', or None (no closed trades yet)."""
    j = load_journal()
    for t in reversed(j["trades"]):
        if t["result"]:
            return t["result"]
    return None


def get_record() -> tuple:
    j = load_journal()
    wins   = sum(1 for t in j["trades"] if t["result"] == "WIN")
    losses = sum(1 for t in j["trades"] if t["result"] == "LOSE")
    return wins, losses


def get_dynamic_risk() -> float:
    """3% after WIN, 1% after LOSE or on first trade (conservative for prop firm)."""
    last = get_last_result()
    if last == "WIN":
        return 0.02   # 2% after a win on prop firm (still conservative)
    return 0.01       # 1% default / after loss
