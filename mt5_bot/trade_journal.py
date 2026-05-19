"""Trade journal for the MT5 bot — tracks MT5 ticket IDs and signal groups."""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_FILE = Path("trade_journal_mt5.json")


def load_journal() -> dict:
    if JOURNAL_FILE.exists():
        try:
            with open(JOURNAL_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Could not load journal, starting fresh")
    return {"trades": []}


def save_journal(journal: dict):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=2)


def log_order(
    order_ticket: int,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    volume_lots: float,
    signal_id: str = None,
    tp_label: str = None,
) -> None:
    """Log a placed pending order. position_ticket is filled in once the order fills."""
    journal = load_journal()
    journal["trades"].append({
        "order_ticket": order_ticket,        # MT5 order ticket (pending)
        "position_ticket": None,             # MT5 position ticket (set after fill)
        "signal_id": signal_id,
        "tp_label": tp_label,
        "placed_at": datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "volume_lots": volume_lots,
        "be_moved": False,
        "closed_at": None,
        "close_price": None,
        "pnl": None,
        "result": None,  # "WIN", "LOSE", "BREAK_EVEN", or None
    })
    save_journal(journal)
    logger.info(f"Trade logged [{tp_label or 'TP'}]: {direction} {volume_lots} lots @ {entry}")


def link_position(order_ticket: int, position_ticket: int) -> None:
    """When a pending order fills, link the resulting position ticket back to it."""
    journal = load_journal()
    for trade in journal["trades"]:
        if trade["order_ticket"] == order_ticket and trade.get("position_ticket") is None:
            trade["position_ticket"] = position_ticket
            save_journal(journal)
            return


def find_legs_by_signal(signal_id: str) -> list:
    if not signal_id:
        return []
    journal = load_journal()
    return [t for t in journal["trades"] if t.get("signal_id") == signal_id]


def find_by_position_ticket(position_ticket: int) -> dict:
    journal = load_journal()
    for t in journal["trades"]:
        if t.get("position_ticket") == position_ticket:
            return t
    return None


def mark_be_moved(order_ticket: int) -> None:
    journal = load_journal()
    for trade in journal["trades"]:
        if trade["order_ticket"] == order_ticket:
            trade["be_moved"] = True
            save_journal(journal)
            return


def mark_closed(order_ticket: int, close_price: float, pnl: float, result: str) -> None:
    journal = load_journal()
    for trade in journal["trades"]:
        if trade["order_ticket"] == order_ticket:
            trade["closed_at"] = datetime.utcnow().isoformat() + "Z"
            trade["close_price"] = close_price
            trade["pnl"] = pnl
            trade["result"] = result
            save_journal(journal)
            logger.info(f"Trade closed: order {order_ticket} = {result} P&L ${pnl:.2f}")
            return


def get_win_loss_count() -> tuple:
    journal = load_journal()
    wins = sum(1 for t in journal["trades"] if t.get("result") == "WIN")
    losses = sum(1 for t in journal["trades"] if t.get("result") == "LOSE")
    return wins, losses
