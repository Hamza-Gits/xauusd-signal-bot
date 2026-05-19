"""Telegram → 5ers MT5 signal automation with multi-leg + prop firm safety.

Mirrors the OANDA bot's behaviour but:
- Routes orders through MetaTrader5 (not REST) — requires MT5 client running.
- Uses USD risk in lot sizing (account is 5ers USD).
- Adds prop firm safety guards:
    * daily loss circuit breaker (3% by default — buffer below 5ers' 5% limit)
    * consecutive loss pause (3 SLs → 60-min cooldown)
    * total drawdown halt (5% by default — buffer below 5ers' 8-10% limit)
"""
import asyncio
import hashlib
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from mt5_client import MT5Client, MT5Error
from prop_firm_guard import PropFirmGuard
from risk_manager import RiskManager
from signal_parser import Signal, parse_signal
from telegram_listener import TelegramListener
from telethon.errors import AuthKeyDuplicatedError, AuthKeyError, SessionRevokedError, UserDeactivatedError
from trade_journal import (
    log_order,
    link_position,
    mark_closed,
    mark_be_moved,
    find_legs_by_signal,
    find_by_position_ticket,
    get_win_loss_count,
)


def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("signals_mt5.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("telethon").setLevel(logging.WARNING)


logger = logging.getLogger("main_mt5")

# ---- Globals wired in main_async ----
mt5_client: MT5Client
risk: RiskManager
guard: PropFirmGuard
listener: TelegramListener


# ---- Signal hashing & leg splitting (same scheme as OANDA bot) ----
def _signal_id(signal: Signal) -> str:
    key = f"{signal.direction}:{signal.entry}:{signal.stop_loss}:{signal.tp1}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


LEG_WEIGHTS = {
    3: [0.15, 0.25, 0.60],
    2: [0.35, 0.65],
    1: [1.00],
}

TP_BUFFER = 0.5  # shave TPs toward entry by 0.5 USD to fight broker spread


def _buffered_tp(direction: str, tp_price: float) -> float:
    return (tp_price - TP_BUFFER) if direction == "BUY" else (tp_price + TP_BUFFER)


def _split_lots(total: float, num_legs: int, lot_step: float, min_lot: float) -> list:
    """Weighted split of `total` lots across `num_legs`, respecting broker's lot_step and min_lot."""
    decimals = max(0, -int(math.floor(math.log10(lot_step))))
    legs_wanted = num_legs
    while legs_wanted > 0:
        weights = LEG_WEIGHTS.get(legs_wanted, [1.0])
        legs = []
        for w in weights[:-1]:
            u = math.floor((total * w) / lot_step) * lot_step
            legs.append(round(u, decimals))
        last = round(total - sum(legs), decimals)
        legs.append(last)
        if all(u >= min_lot for u in legs):
            return legs
        legs_wanted -= 1
    return [total]


# ---- Starting balance bootstrap ----
def load_or_init_starting_balance(current_balance: float) -> float:
    """Resolve the IMMOVABLE baseline for max-DD calculations.

    Priority:
      1. MT5_INITIAL_BALANCE env var (recommended — set this explicitly)
      2. Cached value in starting_balance.json (from a previous run)
      3. Auto-init from current balance (LAST RESORT — wrong if you've
         already drawn down before starting the bot)
    """
    path = Path(config.STARTING_BALANCE_FILE)

    # Env var wins — overrides any cached or auto-detected value
    if config.MT5_INITIAL_BALANCE:
        with open(path, "w") as f:
            json.dump({
                "starting_balance": config.MT5_INITIAL_BALANCE,
                "source": "env_var",
                "set_at": datetime.utcnow().isoformat(),
            }, f, indent=2)
        logger.info(f"Starting balance set from env: ${config.MT5_INITIAL_BALANCE:.2f}")
        return config.MT5_INITIAL_BALANCE

    if path.exists():
        with open(path) as f:
            data = json.load(f)
            sb = float(data["starting_balance"])
            logger.info(f"Starting balance loaded from cache: ${sb:.2f}")
            return sb

    # Auto-init fallback — warn loudly because this can be wrong
    logger.warning(
        f"⚠️  No MT5_INITIAL_BALANCE set and no cache file. Auto-initialising "
        f"baseline to current equity ${current_balance:.2f}. If you have ALREADY "
        f"drawn down on this account, max-DD calculations will be wrong. "
        f"Set MT5_INITIAL_BALANCE in .env to the original account size."
    )
    with open(path, "w") as f:
        json.dump({
            "starting_balance": current_balance,
            "source": "auto_init",
            "set_at": datetime.utcnow().isoformat(),
        }, f, indent=2)
    return current_balance


# ---- Telegram notify ----
async def _notify(text: str):
    if not config.NOTIFY_CHAT_ID:
        return
    try:
        await listener.client.send_message(int(config.NOTIFY_CHAT_ID), text)
    except Exception:
        logger.exception("Failed to send Telegram notification")


# ---- Signal handling ----
async def handle_message(text: str):
    signal = parse_signal(text)
    if signal is None:
        return

    logger.info(
        f"Parsed signal: {signal.direction} @ {signal.entry} "
        f"SL={signal.stop_loss} TP1={signal.tp1} TP2={signal.tp2} TP3={signal.tp3}"
    )

    if risk.is_duplicate(signal):
        logger.warning("Duplicate signal — skipping")
        return

    # Prop firm guards
    try:
        equity = mt5_client.get_equity()
    except MT5Error as e:
        logger.error(f"Could not fetch equity: {e}")
        return

    allowed, reason = guard.can_trade(equity)
    if not allowed:
        logger.warning(f"Prop firm guard blocked trade: {reason}")
        await _notify(f"⛔ Signal SKIPPED — {reason}")
        return

    # Sizing
    sym = mt5_client.symbol_info
    total_lots = risk.calculate_lots(
        balance_usd=equity,
        signal=signal,
        contract_size=sym.trade_contract_size,
        min_lot=sym.volume_min,
        lot_step=sym.volume_step,
    )
    if total_lots is None:
        logger.warning("Lot sizing returned None — skipping")
        return

    # TP levels
    tp_levels = [("TP1", signal.tp1)]
    if signal.tp2 is not None:
        tp_levels.append(("TP2", signal.tp2))
    if signal.tp3 is not None:
        tp_levels.append(("TP3", signal.tp3))

    leg_lots = _split_lots(total_lots, len(tp_levels), sym.volume_step, sym.volume_min)
    if len(leg_lots) < len(tp_levels):
        if len(tp_levels) == 3 and len(leg_lots) == 2:
            tp_levels = [tp_levels[0], tp_levels[2]]  # TP1 + TP3
        elif len(tp_levels) == 3 and len(leg_lots) == 1:
            tp_levels = [tp_levels[2]]                # TP3 only
        else:
            tp_levels = tp_levels[: len(leg_lots)]
    logger.info(f"Split {total_lots} lots → {list(zip([l for l, _ in tp_levels], leg_lots))}")

    sid = _signal_id(signal)
    placed = []
    for (tp_label, tp_price), lots in zip(tp_levels, leg_lots):
        placed_tp = _buffered_tp(signal.direction, tp_price)
        try:
            result = mt5_client.place_limit_order(
                direction=signal.direction,
                volume_lots=lots,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=placed_tp,
                comment=f"{sid}-{tp_label}",
            )
        except MT5Error as e:
            logger.error(f"MT5 order failed for {tp_label}: {e}")
            await _notify(f"❌ {tp_label} leg failed: {e}")
            continue
        order_ticket = result.get("order")
        logger.info(f"Order placed [{tp_label}] lots={lots} TP={placed_tp} ticket={order_ticket}")
        log_order(
            order_ticket=order_ticket,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=placed_tp,
            volume_lots=lots,
            signal_id=sid,
            tp_label=tp_label,
        )
        placed.append((tp_label, placed_tp, lots, order_ticket))

    if not placed:
        return

    wins, losses = get_win_loss_count()
    legs_str = "\n".join(f"  {label}: {l} lot @ {tp}" for label, tp, l, _ in placed)
    risk_usd = abs(signal.entry - signal.stop_loss) * sym.trade_contract_size * sum(l for _, _, l, _ in placed)
    await _notify(
        f"✅ {signal.direction} {config.INSTRUMENT} ({len(placed)}-leg) [5ers]\n"
        f"Entry: {signal.entry}  SL: {signal.stop_loss}\n"
        f"Legs:\n{legs_str}\n"
        f"Risk: ${risk_usd:.2f}  | {guard.status_line(equity)}\n"
        f"Record: {wins}W / {losses}L"
    )


# ---- Background tasks ----
async def link_fills_to_positions():
    """When a pending order fills, MT5 gives the resulting position a new ticket.
    Match them up by reading deals history and updating the journal."""
    while True:
        try:
            await asyncio.sleep(20)
            deals = mt5_client.get_closed_deals(hours=6)
            for d in deals:
                # Entry deal — links order to position
                if d.get("entry") == 0:  # DEAL_ENTRY_IN
                    order_t = d.get("order")
                    pos_t = d.get("position_id")
                    if order_t and pos_t:
                        link_position(order_t, pos_t)
        except Exception:
            logger.exception("link_fills_to_positions error")


async def watch_closes_and_manage_runners():
    """Detect closed positions, update journal, trigger BE moves / trails."""
    while True:
        try:
            await asyncio.sleep(30)
            deals = mt5_client.get_closed_deals(hours=12)

            # DEAL_ENTRY_OUT = position closed
            tp1_won_groups = set()
            tp2_won_groups = set()
            for d in deals:
                if d.get("entry") != 1:  # not a closing deal
                    continue
                pos_t = d.get("position_id")
                if not pos_t:
                    continue
                journal_entry = find_by_position_ticket(pos_t)
                if not journal_entry or journal_entry.get("result"):
                    continue
                pnl = float(d.get("profit", 0))
                price = float(d.get("price", 0))
                result = "WIN" if pnl > 0 else "LOSE" if pnl < 0 else "BREAK_EVEN"
                mark_closed(journal_entry["order_ticket"], price, pnl, result)

                label = journal_entry.get("tp_label") or "leg"
                direction = journal_entry.get("direction", "")
                emoji = "🎯" if result == "WIN" else "🛑" if result == "LOSE" else "⚖️"
                verdict = (
                    f"{label} HIT" if result == "WIN"
                    else "SL HIT" if result == "LOSE"
                    else f"{label} BE"
                )
                await _notify(f"{emoji} {verdict} — {direction} @ {price}\nP&L: ${pnl:+.2f}")

                # Update prop firm guard
                guard.record_outcome(won=(result == "WIN"))

                if result == "WIN" and journal_entry.get("signal_id"):
                    if label == "TP1":
                        tp1_won_groups.add(journal_entry["signal_id"])
                    elif label == "TP2":
                        tp2_won_groups.add(journal_entry["signal_id"])

            if tp1_won_groups:
                await _move_runners_to_be(tp1_won_groups)
            if tp2_won_groups:
                await _trail_tp3_to_tp1(tp2_won_groups)
        except Exception:
            logger.exception("watch_closes error")


async def _move_runners_to_be(signal_ids: set):
    try:
        positions = mt5_client.get_open_positions()
    except MT5Error:
        logger.exception("Could not fetch positions for BE")
        return
    pos_by_ticket = {p["ticket"]: p for p in positions}
    for sid in signal_ids:
        legs = find_legs_by_signal(sid)
        if not legs:
            continue
        entry = legs[0]["entry"]
        for leg in legs:
            if leg.get("result") or leg.get("be_moved"):
                continue
            pos_t = leg.get("position_ticket")
            if not pos_t or pos_t not in pos_by_ticket:
                continue
            pos = pos_by_ticket[pos_t]
            try:
                mt5_client.modify_position_sl(pos_t, entry, pos["tp"])
                mark_be_moved(leg["order_ticket"])
                await _notify(f"🛡️ SL → BE on {leg.get('tp_label')} ({leg['direction']} @ {entry})")
            except MT5Error as e:
                logger.warning(f"BE move failed on {pos_t}: {e}")
                await _notify(f"⚠️ BE move FAILED on {leg.get('tp_label')} pos {pos_t}")


async def _trail_tp3_to_tp1(signal_ids: set):
    try:
        positions = mt5_client.get_open_positions()
    except MT5Error:
        logger.exception("Could not fetch positions for trail")
        return
    pos_by_ticket = {p["ticket"]: p for p in positions}
    for sid in signal_ids:
        legs = find_legs_by_signal(sid)
        tp1_leg = next((l for l in legs if l.get("tp_label") == "TP1"), None)
        tp3_leg = next((l for l in legs if l.get("tp_label") == "TP3"), None)
        if not tp1_leg or not tp3_leg or tp3_leg.get("result"):
            continue
        pos_t = tp3_leg.get("position_ticket")
        if not pos_t or pos_t not in pos_by_ticket:
            continue
        pos = pos_by_ticket[pos_t]
        try:
            mt5_client.modify_position_sl(pos_t, tp1_leg["take_profit"], pos["tp"])
            mark_be_moved(tp3_leg["order_ticket"])
            await _notify(
                f"📈 TP3 runner SL → TP1 ({tp1_leg['take_profit']}) "
                f"({tp3_leg['direction']}, profit locked)"
            )
        except MT5Error as e:
            logger.warning(f"Trail failed on {pos_t}: {e}")
            await _notify(f"⚠️ TP3 trail FAILED on pos {pos_t}")


async def cancel_stale_orders():
    """Cancel pending limit orders older than 60 min."""
    STALE_MINUTES = 60
    while True:
        try:
            await asyncio.sleep(300)
            pending = mt5_client.get_pending_orders()
            now_epoch = time.time()
            for o in pending:
                created = o.get("time_setup")
                if not created:
                    continue
                age_min = (now_epoch - created) / 60
                if age_min < STALE_MINUTES:
                    continue
                try:
                    mt5_client.cancel_order(o["ticket"])
                    logger.info(f"Cancelled stale order {o['ticket']} (age {age_min:.0f} min)")
                except MT5Error as e:
                    logger.warning(f"Could not cancel order {o['ticket']}: {e}")
        except Exception:
            logger.exception("cancel_stale_orders error")


# ---- Main ----
async def main_async():
    global mt5_client, risk, guard, listener

    setup_logging()
    logger.info(f"Starting 5ers MT5 bot. Symbol={config.INSTRUMENT}, Risk={config.RISK_PCT:.2%}")

    mt5_client = MT5Client(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
        magic=config.MT5_MAGIC,
        symbol=config.INSTRUMENT,
        path=config.MT5_PATH,
    )
    try:
        mt5_client.connect()
    except MT5Error as e:
        logger.error(f"MT5 connection failed: {e}")
        sys.exit(1)

    current_balance = mt5_client.get_balance()
    starting_balance = load_or_init_starting_balance(current_balance)

    risk = RiskManager(risk_pct=config.RISK_PCT)
    guard = PropFirmGuard(
        starting_balance=starting_balance,
        daily_loss_halt_pct=config.DAILY_LOSS_HALT_PCT,
        consecutive_loss_halt=config.CONSECUTIVE_LOSS_HALT,
        consecutive_loss_pause_min=config.CONSECUTIVE_LOSS_PAUSE_MIN,
        total_dd_halt_pct=config.TOTAL_DD_HALT_PCT,
    )

    if not config.TELEGRAM_SESSION_STRING:
        logger.error("TELEGRAM_SESSION_STRING is empty. Run generate_session.py first.")
        sys.exit(1)

    listener = TelegramListener(
        api_id=config.TELEGRAM_API_ID,
        api_hash=config.TELEGRAM_API_HASH,
        phone=config.TELEGRAM_PHONE,
        group_ids=config.TELEGRAM_GROUP_IDS,
        session_string=config.TELEGRAM_SESSION_STRING,
    )
    listener.on_message = handle_message

    _startup_notified = False

    async def _on_ready():
        nonlocal _startup_notified
        if _startup_notified:
            return
        _startup_notified = True
        wins, losses = get_win_loss_count()
        await _notify(
            f"✅ MT5 Bot online — 🟣 5ERS LIVE\n"
            f"Account: {config.MT5_LOGIN} ({config.MT5_SERVER})\n"
            f"Equity: ${current_balance:.2f}  Starting: ${starting_balance:.2f}\n"
            f"Risk: {config.RISK_PCT:.0%} per signal | Record: {wins}W/{losses}L\n"
            f"{guard.status_line(current_balance)}"
        )

    listener.on_ready = _on_ready

    asyncio.create_task(link_fills_to_positions())
    asyncio.create_task(watch_closes_and_manage_runners())
    asyncio.create_task(cancel_stale_orders())

    # Stay connected forever — VPS runs 24/7
    while True:
        try:
            await listener.start()
            logger.warning("Telegram listener exited. Reconnecting in 10s...")
        except asyncio.CancelledError:
            raise
        except (AuthKeyDuplicatedError, AuthKeyError, SessionRevokedError, UserDeactivatedError) as e:
            logger.error(f"FATAL: Telegram session dead ({type(e).__name__}). Regenerate it.")
            await _notify(f"❌ Telegram session DEAD ({type(e).__name__}). Run generate_session.py.")
            sys.exit(1)
        except Exception:
            logger.exception("Listener crashed. Reconnecting in 30s...")
            await asyncio.sleep(30)
            continue
        await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Shutting down.")
        try:
            mt5_client.disconnect()
        except Exception:
            pass
