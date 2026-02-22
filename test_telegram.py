#!/usr/bin/env python3
"""
test_telegram.py — One-time Telegram connection tester.
Run this FIRST before starting the main alert system.
Success = test message appears on your Telegram app within 5 seconds.
"""

import sys
import requests
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def check_credentials():
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not set in .env file.")
        print("   Edit .env and paste your token from @BotFather.")
        sys.exit(1)
    if not CHAT_ID or CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("❌ ERROR: TELEGRAM_CHAT_ID not set in .env file.")
        print("   Visit: https://api.telegram.org/bot{TOKEN}/getUpdates")
        print("   Send a message to your bot first, then check the URL above.")
        sys.exit(1)


def send_test_message():
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": (
            "✅ <b>NSE Alert Bot is connected and ready!</b>\n\n"
            "You will receive order win alerts here.\n\n"
            "📌 Smallcap 250 + SME stocks monitored\n"
            "🕐 Active during market hours: 09:00–16:00 IST\n"
            "⚡ Scan frequency: every 5 minutes"
        ),
        "parse_mode": "HTML",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        if data.get("ok"):
            print("✅ SUCCESS: Test message sent to Telegram!")
            print(f"   Message ID: {data['result']['message_id']}")
            print("   Check your Telegram app now.")
        else:
            print(f"❌ Telegram API error: {data}")
            print("   Double-check TOKEN and CHAT_ID in .env")
            sys.exit(1)
    except requests.exceptions.Timeout:
        print("❌ Request timed out. Check your internet connection.")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("--- NSE Alert Bot: Telegram Connection Test ---")
    check_credentials()
    print(f"   Token  : {TOKEN[:10]}...{TOKEN[-5:]}")
    print(f"   Chat ID: {CHAT_ID}")
    print("   Sending test message...")
    send_test_message()
