"""Telegram → OANDA XAUUSD signal automation with dynamic position sizing.

Listens to configured Telegram groups, parses XAUUSD signals, and places
limit orders on OANDA with risk-based position sizing.

Dynamic risk: 3% after WIN, 2% after LOSE.
"""
import asyncio
import logging
import sys
import time

import config
from oanda_client import OandaClient, OandaError
from risk_manager import RiskManager
from signal_parser import parse_signal
from telegram_listener import TelegramListener
from telethon.errors import AuthKeyDuplicatedError, AuthKeyError, SessionRevokedError, UserDeactivatedError
from trade_journal import (
    log_order,
    update_closed_trade,
    get_win_loss_count,
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


async def check_closed_trades():
    """Periodically check for closed trades and update journal."""
    from trade_journal import load_journal

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            closed = oanda.get_closed_trades(count=20)

            for trade in closed:
                order_id = str(trade["id"])
                pnl = float(trade.get("realizedPL", 0))
                result = "WIN" if pnl > 0 else "LOSE" if pnl < 0 else "BREAK_EVEN"

                # Check if we already logged this
                journal = load_journal()
                trades_by_id = {t["order_id"]: t for t in journal["trades"]}

                if order_id not in trades_by_id:
                    continue  # Not our order
                if trades_by_id[order_id]["result"]:
                    continue  # Already logged this result

                # Get closing price from the trade
                closing_price = float(trade.get("price", 0))
                update_closed_trade(order_id, closing_price, result)
                wins, losses = get_win_loss_count()
                logger.info(f"Trade history: {wins}W / {losses}L")
        except OandaError:
            logger.exception("Error checking closed trades")
        except Exception:
            logger.exception("Unexpected error in check_closed_trades")


async def handle_message(text: str) -> None:
    signal = parse_signal(text)
    if signal is None:
        logger.debug("Message did not parse as a signal — ignored")
        return

    logger.info(
        f"Parsed signal: {signal.direction} @ {signal.entry} "
        f"SL={signal.stop_loss} TP1={signal.tp1}"
    )

    if risk.is_duplicate(signal):
        logger.warning("Duplicate signal — skipping")
        return

    # Fetch live data
    try:
        balance = oanda.get_account_balance()
        gbp_usd = oanda.get_price("GBP_USD")
    except OandaError as e:
        logger.error(f"Failed to fetch account/price data: {e}")
        return

    risk_manager = RiskManager(
        risk_pct=config.RISK_PCT,
        force_min_units=config.FORCE_MIN_UNITS,
    )
    units = risk_manager.calculate_units(balance, gbp_usd, signal)
    if units is None:
        logger.warning("No units to trade — skipping")
        return

    # Place the order
    try:
        result = oanda.place_limit_order(
            direction=signal.direction,
            units=units,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.tp1,
            instrument=config.INSTRUMENT,
        )
    except OandaError as e:
        logger.error(f"Order placement failed: {e}")
        await _notify(f"❌ Order failed for {signal.direction} @ {signal.entry}: {e}")
        return

    order_tx = result.get("orderCreateTransaction", {})
    order_id = order_tx.get("id", "unknown")
    logger.info(f"Order placed successfully. ID={order_id}")

    # Log to journal
    log_order(
        order_id=order_id,
        direction=signal.direction,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.tp1,
        units=units,
    )

    # Notify
    sl_dist = abs(signal.entry - signal.stop_loss)
    risk_gbp = (sl_dist * units) / gbp_usd
    risk_pct = (risk_gbp / balance) * 100
    wins, losses = get_win_loss_count()

    await _notify(
        f"✅ {signal.direction} XAU/USD\n"
        f"Entry: {signal.entry}\n"
        f"SL: {signal.stop_loss}\n"
        f"TP: {signal.tp1}\n"
        f"Units: {units}  Risk: £{risk_gbp:.2f} ({risk_pct:.2f}%)\n"
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
        await _notify(
            f"✅ Bot online\n"
            f"Balance: £{balance:.2f}\n"
            f"Risk: {config.RISK_PCT:.0%} | Record: {wins}W/{losses}L\n"
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
