"""Parse XAUUSD trading signals from Telegram messages.

Handles two known formats:

Format 1:
    GOLD BUY 4673
    🔷TP1 - 4675.4
    🔷TP2 - 4679
    🔷TP3 - 4683
    🔶SL - 4664

Format 2:
    XAUUSD | Potential upward movement
    XAUUSD | BUY 4672
    ❌ Stop Loss 4665 (70 pips)
    ✅TP1 4675
    ✅TP2 4680
    ✅TP3 4685
"""
import re
from dataclasses import dataclass
from typing import Optional

NUMBER = r"([0-9]+(?:\.[0-9]+)?)"

# Direction + entry — works for both formats. Allows optional "XAUUSD |" or "GOLD" prefix
# on the same line, plus any decoration around BUY/SELL.
RE_DIRECTION = re.compile(
    r"(?:GOLD|XAU\s*/?\s*USD|XAUUSD)[^\n]*?\b(BUY|SELL)\b[^\n0-9]*" + NUMBER,
    re.IGNORECASE,
)

# Stop loss — matches "SL - 4664", "SL: 4664", "Stop Loss 4665", "SL 4665"
RE_SL = re.compile(
    r"(?:Stop\s*Loss|\bSL\b)\s*[-–:]?\s*" + NUMBER,
    re.IGNORECASE,
)

RE_TP1 = re.compile(r"\bTP\s*1\b\s*[-–:]?\s*" + NUMBER, re.IGNORECASE)
RE_TP2 = re.compile(r"\bTP\s*2\b\s*[-–:]?\s*" + NUMBER, re.IGNORECASE)
RE_TP3 = re.compile(r"\bTP\s*3\b\s*[-–:]?\s*" + NUMBER, re.IGNORECASE)


@dataclass
class Signal:
    direction: str          # "BUY" or "SELL"
    entry: float
    stop_loss: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]
    raw_text: str


def _search_float(pattern: re.Pattern, text: str) -> Optional[float]:
    m = pattern.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (ValueError, IndexError):
        return None


def parse_signal(text: str) -> Optional[Signal]:
    """Return a Signal if the text contains a valid XAUUSD signal, else None.

    Requires at minimum: direction, entry, stop_loss, tp1. tp2/tp3 are optional.
    """
    if not text:
        return None

    m = RE_DIRECTION.search(text)
    if not m:
        return None

    direction = m.group(1).upper()
    try:
        entry = float(m.group(2))
    except (ValueError, IndexError):
        return None

    stop_loss = _search_float(RE_SL, text)
    tp1 = _search_float(RE_TP1, text)
    tp2 = _search_float(RE_TP2, text)
    tp3 = _search_float(RE_TP3, text)

    if stop_loss is None or tp1 is None:
        return None

    # Sanity check: SL/TP must be on correct sides of entry
    if direction == "BUY" and (stop_loss >= entry or tp1 <= entry):
        return None
    if direction == "SELL" and (stop_loss <= entry or tp1 >= entry):
        return None

    return Signal(
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        raw_text=text,
    )
