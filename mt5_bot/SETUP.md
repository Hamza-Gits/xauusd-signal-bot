# 5ers MT5 Bot — Setup Guide

## 1. Windows VPS prep

You need a Windows VPS (Ubuntu won't work — MT5 only runs on Windows or via Wine which is unreliable). Suggested providers:

- **Contabo Windows VPS** — ~£8/mo, good value
- **ForexVPS** — ~£20/mo, lower latency to broker
- **Vultr High-Frequency Windows** — ~£10/mo

RDP into the VPS once it's provisioned.

## 2. Install MT5

1. Download the MT5 installer from your 5ers broker (NOT generic MetaQuotes MT5 — your prop firm uses a branded version).
2. Install. Use default install path (`C:\Program Files\MetaTrader 5\`).
3. Launch MT5. File → Login to Trade Account.
4. Enter your 5ers credentials. Verify you see your $5K balance.
5. **CRITICAL:** Test a manual trade (1 micro lot, close immediately). Confirms execution works.

## 3. Install Python

1. Download Python 3.11+ from python.org.
2. **CHECK "Add Python to PATH"** during install.
3. Open PowerShell, verify: `python --version`

## 4. Set up the bot

```powershell
# Clone the repo (replace with your URL)
cd C:\
git clone https://github.com/Hamza-Gits/xauusd-signal-bot.git
cd xauusd-signal-bot\mt5_bot

# Install dependencies
pip install -r requirements.txt
```

## 5. Generate a Telegram session string

You need a SECOND Telegram account (different phone number from the OANDA bot's). Running two Telethon clients on the same account triggers `AuthKeyDuplicatedError` and kills both.

1. Get API credentials at https://my.telegram.org/apps for the 2nd account.
2. Copy `generate_session.py` from the OANDA bot folder into `mt5_bot/`.
3. Set env vars and run:
   ```powershell
   $env:TELEGRAM_API_ID="..."
   $env:TELEGRAM_API_HASH="..."
   python generate_session.py
   ```
4. Save the printed string — you'll need it in step 6.

## 6. Configure .env

Copy `.env.example` to `.env` and fill in your real values:

```powershell
copy .env.example .env
notepad .env
```

- `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` — from the 5ers welcome email
- `MT5_INSTRUMENT` — usually `XAUUSD`, but check in MT5's Market Watch what it's called on YOUR broker (could be `GOLD`, `XAUUSDm`, etc.). Bot will tell you possible names if you get it wrong.
- `TELEGRAM_SESSION_STRING` — from step 5
- `TELEGRAM_GROUP_IDS` — `-1003725317305` for Qasem
- `NOTIFY_CHAT_ID` — your own Telegram chat ID (so the bot can DM you status)
- Leave risk values at defaults for first run (1% per signal, 3% daily halt, 5% total DD halt)

## 7. Verify MT5 connection BEFORE running the bot

Run this quick test:

```powershell
python -c "import MetaTrader5 as mt5; mt5.initialize(login=YOUR_LOGIN, password='YOUR_PWD', server='YOUR_SERVER'); print(mt5.account_info())"
```

Should print your account info. If `None` or error → MT5 setup is wrong, fix that first.

## 8. Run the bot

```powershell
python main.py
```

You should see:
1. Log: `MT5 connected. Account ...`
2. Log: `Telegram listener connected as ...`
3. Telegram DM: `✅ MT5 Bot online — 🟣 5ERS LIVE`

## 9. Keep it running (so you can disconnect RDP)

The bot needs to run continuously. To survive RDP disconnects:

**Option A: Run as a Windows scheduled task** (simplest)
- Task Scheduler → Create Task
- Trigger: At startup
- Action: `python C:\xauusd-signal-bot\mt5_bot\main.py`
- Run whether user is logged on or not

**Option B: NSSM (run as Windows service)**
- Download NSSM, register `python main.py` as a service.
- Auto-restarts on crash.

## 10. Safety checklist before walking away

- [ ] MT5 is logged in and showing your $5K balance
- [ ] Bot startup notification arrived on Telegram
- [ ] Test signal: forward a Qasem message manually to confirm parsing works (or wait for a real one)
- [ ] First trade fills correctly in MT5 (check Trade tab)
- [ ] First Telegram TP/SL notification matches what MT5 shows
- [ ] `prop_firm_state.json` was created in the working directory (the bot writes it)

## Prop firm safety summary

The bot has THREE automatic halts to protect your 5ers account:

| Trigger | Threshold | Action |
|---|---|---|
| Daily loss | -3% of day-start equity | No new signals today (resets at 22:00 UTC) |
| Consecutive losses | 3 SLs in a row | Pause for 60 min |
| Total drawdown | -5% from $5K starting balance | Hard halt — bot stops permanently until you restart it |

All three trip BEFORE 5ers' actual limits (5% daily, 8-10% total) to give a safety buffer.

## Files the bot writes (in working dir)

- `signals_mt5.log` — runtime log
- `trade_journal_mt5.json` — every signal + outcome
- `prop_firm_state.json` — daily loss + streak tracking (resets each broker day)
- `starting_balance.json` — frozen baseline for total-DD calculation

**Don't delete `starting_balance.json` unless you want the bot to re-initialise to current equity.**
