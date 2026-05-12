"""Trade journal: log all orders and track their outcomes."""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_FILE = Path("trade_journal.json")


def load_journal() -> dict:
    """Load existing journal or create empty."""
    if JOURNAL_FILE.exists():
        try:
            with open(JOURNAL_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Could not load journal, starting fresh")
    return {"trades": []}


def save_journal(journal: dict):
    """Save journal to disk."""
    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=2)


def log_order(
    order_id: str,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    units: float,
) -> None:
    """Log a newly placed order."""
    journal = load_journal()
    journal["trades"].append({
        "order_id": order_id,
        "placed_at": datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "units": units,
        "closed_at": None,
        "close_price": None,
        "result": None,  # "WIN", "LOSE", None (still open)
    })
    save_journal(journal)
    logger.info(f"Trade logged: {direction} {units} units @ {entry}")


def update_closed_trade(order_id: str, close_price: float, result: str) -> None:
    """Mark a trade as closed with WIN/LOSE result.

    result: "WIN" if closed at TP, "LOSE" if closed at SL
    """
    journal = load_journal()
    for trade in journal["trades"]:
        if trade["order_id"] == order_id:
            trade["closed_at"] = datetime.utcnow().isoformat() + "Z"
            trade["close_price"] = close_price
            trade["result"] = result
            save_journal(journal)
            logger.info(f"Trade closed: order {order_id} = {result} @ {close_price}")
            return
    logger.warning(f"Order {order_id} not found in journal")


def get_last_trade_result() -> str:
    """Return "WIN", "LOSE", or None (no closed trades yet)."""
    journal = load_journal()
    for trade in reversed(journal["trades"]):
        if trade["result"]:  # Has a result (WIN or LOSE)
            return trade["result"]
    return None


def get_win_loss_count() -> tuple:
    """Return (wins, losses) from closed trades."""
    journal = load_journal()
    wins = sum(1 for t in journal["trades"] if t["result"] == "WIN")
    losses = sum(1 for t in journal["trades"] if t["result"] == "LOSE")
    return wins, losses
