"""MT5 AquaFunded signal bot — Telegram → MetaAPI → AquaFunded MT5.

Separate and completely independent from the OANDA bot.
Risk: 1% after loss / first trade, 2% after win (prop-firm conservative).
"""
import asyncio
import logging
import sys
import os

# Allow imports from parent folder (signal_parser shared)
sys.path.insert(0, os.path.dirname(__file__))

import config_mt5 as config
from mt5_client import MT5Client, MT5Error
from risk_manager_mt5 import RiskManagerMT5
from signal_parser import parse_signal
from trade_journal_mt5 import log_order, get_dynamic_risk, get_record

# Telethon listener (reuse same logic)
from telethon import TelegramClient, events
from telethon.sessions import StringSession


def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("mt5_signals.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("telethon").setLevel(logging.WARNING)


logger = logging.getLogger("main_mt5")

mt5: MT5Client
risk: RiskManagerMT5
tg_client: TelegramClient


def _coerce_group_id(g: str):
    g = g.strip()
    return int(g) if g.lstrip("-").isdigit() else g


async def handle_message(text: str):
    signal = parse_signal(text)
    if signal is None:
        return

    logger.info(
        f"Signal: {signal.direction} @ {signal.entry} "
        f"SL={signal.stop_loss} TP1={signal.tp1}"
    )

    if risk.is_duplicate(signal.direction, signal.entry, signal.stop_loss, signal.tp1):
        logger.warning("Duplicate signal — skipped")
        return

    # Dynamic risk
    risk_pct = get_dynamic_risk()
    risk.risk_pct = risk_pct

    try:
        balance = await mt5.get_balance()
    except MT5Error as e:
        logger.error(f"Could not fetch balance: {e}")
        return

    sl_distance = abs(signal.entry - signal.stop_loss)
    lots = risk.calculate_lots(balance, sl_distance)
    if lots is None:
        return

    actual_risk = sl_distance * 100 * lots
    wins, losses = get_record()
    logger.info(
        f"Placing {signal.direction} {lots} lots @ {signal.entry} | "
        f"Risk: ${actual_risk:.2f} ({risk_pct:.2%}) | Record: {wins}W/{losses}L"
    )

    try:
        result = await mt5.place_limit_order(
            direction=signal.direction,
            volume=lots,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.tp1,
            symbol=config.SYMBOL,
        )
    except MT5Error as e:
        logger.error(f"Order failed: {e}")
        await _notify(f"❌ MT5 order failed: {e}")
        return

    order_id = result.get("orderId", result.get("id", "unknown"))
    logger.info(f"Order placed. ID={order_id}")

    log_order(order_id, signal.direction, signal.entry,
              signal.stop_loss, signal.tp1, lots)

    await _notify(
        f"✅ AquaFunded {signal.direction} XAUUSD\n"
        f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.tp1}\n"
        f"Lots: {lots} | Risk: ${actual_risk:.2f} ({risk_pct:.2%})\n"
        f"Record: {wins}W / {losses}L"
    )


async def _notify(text: str):
    if not config.NOTIFY_CHAT_ID:
        return
    try:
        await tg_client.send_message(int(config.NOTIFY_CHAT_ID), text)
    except Exception:
        logger.exception("Notification failed")


async def main():
    global mt5, risk, tg_client

    setup_logging()
    logger.info("MT5 AquaFunded bot starting up...")

    # Connect directly to AquaFunded MT5 terminal (no third-party service)
    mt5 = MT5Client(config.MT5_LOGIN, config.MT5_PASSWORD, config.MT5_SERVER)
    try:
        await mt5.connect()
        balance = await mt5.get_balance()
        wins, losses = get_record()
        logger.info(f"AquaFunded connected. Balance: ${balance:.2f}")
        logger.info(f"Trade history: {wins}W / {losses}L")
        logger.info(f"Next trade risk: {get_dynamic_risk():.2%}")
    except MT5Error as e:
        logger.error(f"MT5 connection failed: {e}")
        sys.exit(1)

    risk = RiskManagerMT5(
        risk_pct=get_dynamic_risk(),
        min_lot=config.MIN_LOT,
        lot_precision=config.LOT_PRECISION,
    )

    if not config.TELEGRAM_SESSION_STRING:
        logger.error("TELEGRAM_SESSION_STRING missing. Run generate_session.py.")
        sys.exit(1)

    # Build Telegram client
    group_ids = [_coerce_group_id(g) for g in config.TELEGRAM_GROUP_IDS]
    tg_client = TelegramClient(
        StringSession(config.TELEGRAM_SESSION_STRING),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )

    await tg_client.start(phone=lambda: config.TELEGRAM_PHONE)
    me = await tg_client.get_me()
    logger.info(
        f"Telegram connected as {me.username or me.first_name} ({me.id}). "
        f"Monitoring: {group_ids}"
    )

    @tg_client.on(events.NewMessage(chats=group_ids))
    async def _handler(event):
        text = event.message.text or ""
        if text:
            logger.info(f"Message from {event.chat_id}: {text[:150]!r}")
            try:
                await handle_message(text)
            except Exception:
                logger.exception("handle_message raised")

    logger.info("Listening for signals...")
    await tg_client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down.")
