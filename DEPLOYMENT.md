# Deployment Guide

## 1. Local setup & test (do this first)

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
copy .env.template .env          # or `cp` on Linux/Mac
```

Fill in the values in `.env`:

| Variable | Where to get it |
|---|---|
| `OANDA_API_KEY` | https://www.oanda.com → Account → Manage API Access |
| `OANDA_ACCOUNT_ID` | OANDA dashboard, e.g. `001-004-1234567-001` |
| `OANDA_ENV` | `practice` for testing, `live` for real money |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | https://my.telegram.org → API development tools |
| `TELEGRAM_PHONE` | Your Telegram phone in international format (e.g. `+447700900123`) |
| `TELEGRAM_GROUP_IDS` | Forward a message from the target group to `@userinfobot` to get the ID. Comma-separate multiple groups. |

## 2. Generate Telegram session string

This must be done **locally** because it needs you to enter the SMS/app login code interactively.

```bash
python generate_session.py
```

It prints a long string. Paste it into `.env` as `TELEGRAM_SESSION_STRING=...`.

## 3. Test signal parser

```bash
python -m unittest tests/test_parser.py
```

All tests should pass — this requires no network/credentials.

## 4. Sandbox dry-run

Set `OANDA_ENV=practice` in `.env`, run:

```bash
python main.py
```

You should see:
```
OANDA connected. Account balance: £...
Telegram listener connected as ...
Listening for signals...
```

Send a sample signal into one of the monitored groups (or post it yourself if you're an admin). Check OANDA's practice account dashboard — a pending limit order should appear.

## 5. Deploy to Railway

1. Push this folder to a GitHub repo (the `.gitignore` already excludes `.env` and the session file).
2. Go to https://railway.app → New Project → Deploy from GitHub repo.
3. Once detected, open the project → **Variables** → add every variable from your `.env` (including `TELEGRAM_SESSION_STRING`).
4. Railway will install `requirements.txt` and run `python main.py` from the `Procfile`.
5. Open **Deployments → View Logs**. You should see `Listening for signals...`.

### Switching to live
When you've verified practice trades work end-to-end, set `OANDA_ENV=live` in the Railway dashboard and redeploy.

## 6. Notes & caveats

- **OANDA min trade size for XAU_USD is 0.1 units (0.1 oz)** with 1-decimal precision. Code rounds units down to nearest 0.1 so we never exceed the 1% risk budget.
- **Position size on the £10k demo**: at 1% risk and typical 6–11-point SLs, calculated units are 12–22 — well above the 0.1 minimum, so every trade is exactly 1% risk.
- **Group IDs**: Telegram supergroup IDs are negative numbers starting with `-100`. Channels work the same way.
- **The Telethon session is tied to your phone number.** Don't share `TELEGRAM_SESSION_STRING` — it grants full account access.
- **Duplicate signals**: the same direction/entry/SL/TP1 won't trigger twice within the last 10 signals — protects against repost spam in groups.
- **SSL on Windows**: the OANDA client uses `truststore` to read Windows' native CA store. Without it, `certifi`'s bundle can mismatch and connection fails.
