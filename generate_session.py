"""One-time helper: log in to Telegram and print a StringSession.

Run this locally (NOT on Railway) on a machine where you can receive the
SMS/app code:

    python generate_session.py

It prints a long string. Paste that into your .env as
TELEGRAM_SESSION_STRING=... so the bot can re-authenticate on Railway
without prompting.
"""
import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        phone = input("Enter your phone number (e.g. +447700900123): ").strip()
        await client.send_code_request(phone)
        code = input("Enter the code Telegram sent to your app: ").strip()
        await client.sign_in(phone, code)

    print("\n=== Copy the line below into TELEGRAM_SESSION_STRING in .env ===\n")
    print(client.session.save())
    print("\n=== End of session string ===\n")
    await client.disconnect()


asyncio.run(main())
