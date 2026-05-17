"""Telegram → OANDA XAUUSD signal automation with multi-leg scale-out.

Listens to configured Telegram groups, parses XAUUSD signals, and places
LIMIT orders on OANDA with risk-based position sizing.

Strategy:
- Each signal is split into up to 3 sub-orders (legs) targeting TP1/TP2/TP3,
  sharing the same SL. Total risk = config.RISK_PCT (default 3%).
- When the TP1 leg closes in profit, the SL on the remaining open legs (TP2,
  TP3) is moved to the entry price (breakeven), so the runners become
  free-money positions.
"""
import asyncio
import hashlib
import logging
import math
import sys
import time

import config
from oanda_client import OandaClient, OandaError
from risk_manager import RiskManager
from signal_parser import Signal, parse_signal
from telegram_listener import TelegramListener
from telethon.errors import AuthKeyDuplicatedError, AuthKeyError, SessionRevokedError, UserDeactivatedError
from trade_journal import (
    log_order,
    update_closed_trade,
    get_win_loss_count,
    find_legs_by_signal,
    mark_be_moved,
)


def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("signals.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


logger = logging.getLogger("main")


# ---- Globals wired in main_async() ----
oanda: OandaClient
risk: RiskManager
listener: TelegramListener
check_closed_trades_task: asyncio.Task = None


def _signal_id(signal: Signal) -> str:
    """Stable short hash that identifies a signal group across legs."""
    key = f"{signal.direction}:{signal.entry}:{signal.stop_loss}:{signal.tp1}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _split_units(total: float, num_legs: int, precision: int = 1, min_size: float = 0.1) -> list:
    """Split `total` units across `num_legs`, each ≥ min_size, rounded down to precision."""
    step = 10 ** -precision
    legs_wanted = num_legs
    while legs_wanted > 1:
        per = math.floor((total / legs_wanted) / step) * step
        per = round(per, precision)
        if per >= min_size:
            legs = [per] * (legs_wanted - 1)
            last = round(total - per * (legs_wanted - 1), precision)
            if last >= min_size:
                legs.append(last)
                return legs
        legs_wanted -= 1
    return [total]


async def check_closed_trades():
    """Poll OANDA for closed trades, update journal, and move runners to BE."""
    from trade_journal import load_journal

    while True:
        try:
            await asyncio.sleep(30)  # Check every 30s for fast BE move on TP1
            closed = oanda.get_closed_trades(count=50)
            journal = load_journal()

            # Build lookup tables: by client_id (preferred) and by open-order id.
            by_client_id = {
                t.get("client_id"): t
                for t in journal["trades"]
                if t.get("client_id")
            }
            by_order_id = {t["order_id"]: t for t in journal["trades"]}

            # Track signal groups that just had a winning leg close — we'll
            # move SL to BE on their remaining open legs after this pass.
            newly_won_groups = set()

            for trade in closed:
                ext_id = (trade.get("clientExtensions") or {}).get("id")
                journal_entry = by_client_id.get(ext_id) if ext_id else None

                # Fallback: match by the order that opened the trade.
                if journal_entry is None:
                    open_order_id = str(trade.get("openOrderID") or trade.get("openOrderId") or "")
                    journal_entry = by_order_id.get(open_order_id)

                if journal_entry is None:
                    continue  # Not one of our trades
                if journal_entry.get("result"):
                    continue  # Already booked

                pnl = float(trade.get("realizedPL", 0))
                result = "WIN" if pnl > 0 else "LOSE" if pnl < 0 else "BREAK_EVEN"
                closing_price = float(trade.get("price", 0))
                update_closed_trade(journal_entry["order_id"], closing_price, result)

                if result == "WIN" and journal_entry.get("signal_id"):
                    newly_won_groups.add(journal_entry["signal_id"])

            # For every signal group that just had a leg win, move SL on the
            # other (still-open) legs to the entry price.
            if newly_won_groups:
                await _move_runners_to_breakeven(newly_won_groups)

            if newly_won_groups or closed:
                wins, losses = get_win_loss_count()
                logger.info(f"Trade history: {wins}W / {losses}L")
        except OandaError:
            logger.exception("Error checking closed trades")
        except Exception:
            logger.exception("Unexpected error in check_closed_trades")


async def _move_runners_to_breakeven(signal_ids: set):
    """For each signal group, push SL on still-open legs to the entry price."""
    try:
        open_trades = oanda.get_open_trades()
    except OandaError:
        logger.exception("Could not fetch open trades for BE move")
        return

    # Index open trades by clientExtensions.id (set as tradeClientExtensions.id at order time).
    open_by_client_id = {}
    for ot in open_trades:
        cid = (ot.get("clientExtensions") or {}).get("id")
        if cid:
            open_by_client_id[cid] = ot

    for sid in signal_ids:
        legs = find_legs_by_signal(sid)
        if not legs:
            continue
        entry_price = legs[0]["entry"]  # all legs share the same entry
        for leg in legs:
            if leg.get("result"):
                continue  # already closed
            if leg.get("be_moved"):
                continue  # already moved
            client_id = leg.get("client_id")
            ot = open_by_client_id.get(client_id) if client_id else None
            if ot is None:
                continue  # leg not currently open (maybe not yet filled, or already closed)
            trade_id = str(ot["id"])
            try:
                oanda.modify_trade_sl(trade_id, entry_price)
                mark_be_moved(leg["order_id"])
                logger.info(
                    f"BE move: signal {sid} leg {leg.get('tp_label')} "
                    f"trade {trade_id} → SL@{entry_price}"
                )
                await _notify(
                    f"🛡️ SL → breakeven on {leg.get('tp_label')} leg "
                    f"({leg['direction']} @ {entry_price})"
                )
            except OandaError as e:
                logger.warning(f"Could not move SL on trade {trade_id}: {e}")


async def handle_message(text: str) -> None:
    signal = parse_signal(text)
    if signal is None:
        logger.debug("Message did not parse as a signal — ignored")
        return

    logger.info(
        f"Parsed signal: {signal.direction} @ {signal.entry} "
        f"SL={signal.stop_loss} TP1={signal.tp1} TP2={signal.tp2} TP3={signal.tp3}"
    )

    if risk.is_duplicate(signal):
        logger.warning("Duplicate signal — skipping")
        return

    # Fetch live data — account summary gives us balance AND margin info,
    # so we can pre-check that the trade we're about to place actually fits.
    try:
        account = oanda.get_account_summary()
        balance = float(account["balance"])
        margin_available = float(account.get("marginAvailable", 0))
        margin_used = float(account.get("marginUsed", 0))
        gbp_usd = oanda.get_price("GBP_USD")
    except OandaError as e:
        logger.error(f"Failed to fetch account/price data: {e}")
        return

    risk_manager = RiskManager(
        risk_pct=config.RISK_PCT,
        force_min_units=config.FORCE_MIN_UNITS,
    )
    total_units = risk_manager.calculate_units(balance, gbp_usd, signal)
    if total_units is None:
        logger.warning("No units to trade — skipping")
        return

    # ---- Margin safety check ----
    # Estimate margin for this position. XAU at 1:30 retail leverage needs
    # ~3.33% of notional; we use a 4% safety estimate (covers 1:25 too).
    # If placing this trade would leave us with less than 30% free margin
    # of the total account NAV, we skip it — protects against margin-call
    # cascades when 2-3 signals fire in close succession on a small account.
    notional_gbp = (total_units * signal.entry) / gbp_usd
    est_margin_required = notional_gbp * 0.04  # 4% — slightly conservative
    nav = balance + margin_used  # rough NAV proxy
    free_after = margin_available - est_margin_required
    free_after_pct = (free_after / nav * 100) if nav > 0 else 0

    logger.info(
        f"Margin check: balance=£{balance:.2f}, free=£{margin_available:.2f}, "
        f"used=£{margin_used:.2f}, est_required=£{est_margin_required:.2f}, "
        f"free_after_pct={free_after_pct:.1f}%"
    )

    if free_after < 0:
        logger.warning(
            f"Insufficient margin: need ~£{est_margin_required:.2f}, "
            f"have £{margin_available:.2f}. Skipping signal."
        )
        await _notify(
            f"⚠️ Skipped {signal.direction} @ {signal.entry} — not enough free margin "
            f"(need ~£{est_margin_required:.2f}, have £{margin_available:.2f})"
        )
        return

    if free_after_pct < 30:
        logger.warning(
            f"Margin too tight after this trade ({free_after_pct:.1f}% free). "
            f"Skipping to keep buffer for later signals."
        )
        await _notify(
            f"⚠️ Skipped {signal.direction} @ {signal.entry} — would leave only "
            f"{free_after_pct:.1f}% free margin (need 30% buffer)"
        )
        return

    # Build list of (tp_label, tp_price) — only TPs the signal actually provided.
    tp_levels = [("TP1", signal.tp1)]
    if signal.tp2 is not None:
        tp_levels.append(("TP2", signal.tp2))
    if signal.tp3 is not None:
        tp_levels.append(("TP3", signal.tp3))

    # Try to split units across all available TPs; fall back to fewer legs if
    # rounding takes us below OANDA's minimum trade size.
    leg_units = _split_units(total_units, len(tp_levels), precision=1, min_size=0.1)
    if len(leg_units) < len(tp_levels):
        tp_levels = tp_levels[: len(leg_units)]
    logger.info(
        f"Splitting {total_units} units across {len(leg_units)} legs: "
        f"{list(zip([l for l, _ in tp_levels], leg_units))}"
    )

    sid = _signal_id(signal)
    placed = []  # list of (tp_label, tp_price, units, order_id)

    for (tp_label, tp_price), units in zip(tp_levels, leg_units):
        client_id = f"{sid}-{tp_label}"
        try:
            result = oanda.place_limit_order(
                direction=signal.direction,
                units=units,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=tp_price,
                instrument=config.INSTRUMENT,
                client_id=client_id,
                client_tag=sid,
            )
        except OandaError as e:
            logger.error(f"Order placement failed for {tp_label}: {e}")
            await _notify(f"❌ {tp_label} leg failed for {signal.direction} @ {signal.entry}: {e}")
            continue

        order_id = result.get("orderCreateTransaction", {}).get("id", "unknown")
        logger.info(f"Order placed [{tp_label}] units={units} ID={order_id}")
        log_order(
            order_id=order_id,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=tp_price,
            units=units,
            signal_id=sid,
            tp_label=tp_label,
            client_id=client_id,
        )
        placed.append((tp_label, tp_price, units, order_id))

    if not placed:
        return  # All legs failed; nothing to report beyond the per-leg errors above.

    # Notify (full picture across all legs)
    sl_dist = abs(signal.entry - signal.stop_loss)
    total_units_placed = sum(u for _, _, u, _ in placed)
    risk_gbp = (sl_dist * total_units_placed) / gbp_usd
    risk_pct = (risk_gbp / balance) * 100
    wins, losses = get_win_loss_count()

    legs_str = "\n".join(
        f"  {label}: {u} u @ {tp}" for label, tp, u, _ in placed
    )
    await _notify(
        f"✅ {signal.direction} XAU/USD ({len(placed)}-leg)\n"
        f"Entry: {signal.entry}\n"
        f"SL: {signal.stop_loss}\n"
        f"Legs:\n{legs_str}\n"
        f"Total units: {total_units_placed}  Risk: £{risk_gbp:.2f} ({risk_pct:.2f}%)\n"
        f"Record: {wins}W / {losses}L"
    )


async def _notify(text: str) -> None:
    if not config.NOTIFY_CHAT_ID:
        return
    try:
        await listener.client.send_message(int(config.NOTIFY_CHAT_ID), text)
    except Exception:
        logger.exception("Failed to send self-notification")


async def main_async():
    global oanda, risk, listener, check_closed_trades_task

    setup_logging()
    logger.info(f"Starting up. OANDA env={config.OANDA_ENV}, instrument={config.INSTRUMENT}")

    oanda = OandaClient(
        api_key=config.OANDA_API_KEY,
        account_id=config.OANDA_ACCOUNT_ID,
        env=config.OANDA_ENV,
    )

    # Sanity check OANDA connectivity at startup
    try:
        balance = oanda.get_account_balance()
        logger.info(f"OANDA connected. Account balance: £{balance:.2f}")
    except OandaError as e:
        logger.error(f"Could not reach OANDA: {e}")
        sys.exit(1)

    # Show trade history
    wins, losses = get_win_loss_count()
    logger.info(f"Trade history: {wins}W / {losses}L")

    risk = RiskManager(
        risk_pct=config.RISK_PCT,
        force_min_units=config.FORCE_MIN_UNITS,
    )

    if not config.TELEGRAM_SESSION_STRING:
        logger.error(
            "TELEGRAM_SESSION_STRING is empty. Run generate_session.py locally "
            "first, then paste the printed string into your .env."
        )
        sys.exit(1)

    listener = TelegramListener(
        api_id=config.TELEGRAM_API_ID,
        api_hash=config.TELEGRAM_API_HASH,
        phone=config.TELEGRAM_PHONE,
        group_ids=config.TELEGRAM_GROUP_IDS,
        session_string=config.TELEGRAM_SESSION_STRING,
    )
    listener.on_message = handle_message

    # Fire a one-shot startup notification the first time the listener connects,
    # so the user gets a Telegram heartbeat confirming the bot is alive and
    # which groups it's actually watching.
    _startup_notified = False

    async def _on_ready():
        nonlocal _startup_notified
        if _startup_notified:
            return
        _startup_notified = True
        env_emoji = "🔴 LIVE" if config.OANDA_ENV == "live" else "🟢 PRACTICE"
        await _notify(
            f"✅ Bot online — {env_emoji}\n"
            f"Account: {config.OANDA_ACCOUNT_ID}\n"
            f"Balance: £{balance:.2f}\n"
            f"Risk: {config.RISK_PCT:.0%} per signal | Record: {wins}W/{losses}L\n"
            f"Groups: {len(config.TELEGRAM_GROUP_IDS)} monitored"
        )

    listener.on_ready = _on_ready

    # Start background task to check for closed trades
    check_closed_trades_task = asyncio.create_task(check_closed_trades())

    # Exit cleanly after 330 min so GitHub Actions marks the job as SUCCESS.
    # The next scheduled run (every 6 h) picks up immediately after.
    deadline = time.monotonic() + 330 * 60

    # Auto-reconnect loop — survives Telegram disconnects
    while True:
        if time.monotonic() >= deadline:
            logger.info("330-minute runtime reached — exiting cleanly for scheduled restart.")
            return

        try:
            await listener.start()
            logger.warning("Telegram listener exited cleanly. Reconnecting in 10s...")
        except asyncio.CancelledError:
            raise  # let asyncio.run() handle proper shutdown
        except (AuthKeyDuplicatedError, AuthKeyError, SessionRevokedError, UserDeactivatedError) as e:
            # Session is permanently dead — retrying will never work. Exit so the
            # workflow run ends quickly instead of looping for 6h. The user must
            # regenerate TELEGRAM_SESSION_STRING locally and update the GitHub secret.
            logger.error(
                "FATAL: Telegram session is dead (%s). "
                "Regenerate it locally with `python generate_session.py` and update "
                "the TELEGRAM_SESSION_STRING secret in GitHub.",
                type(e).__name__,
            )
            await _notify(
                f"❌ Telegram session DEAD ({type(e).__name__}).\n"
                f"Run generate_session.py locally and update the GitHub secret."
            )
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
