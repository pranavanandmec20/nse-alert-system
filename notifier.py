#!/usr/bin/env python3
"""
notifier.py — All three notification channels:
  1. Telegram Mobile Alert (highest priority)
  2. macOS Desktop Notification (via osascript — no extra packages needed)
  3. Terminal + scan_log.txt (audit trail)
"""

import os
import subprocess
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOG_FILE = os.path.join(os.path.dirname(__file__), "scan_log.txt")

# ── Logging setup (file + console) ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("NSEAlert")


# ── Channel 1: Telegram ──────────────────────────────────────────────────────

def send_telegram(text: str, retries: int = 3) -> bool:
    """Send a plain or HTML message to Telegram. Returns True on success."""
    if not TOKEN or not CHAT_ID:
        logger.warning("Telegram credentials missing — skipping Telegram notification.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("ok"):
                return True
            logger.error(f"Telegram API error (attempt {attempt}): {data}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram network error (attempt {attempt}): {e}")
    return False


def send_alert_telegram(symbol: str, keyword: str, order_value: str,
                         desc: str, timestamp: str, is_sme: bool = False,
                         markets_open: bool = True) -> bool:
    """Send a formatted order-win alert to Telegram."""
    desc_truncated = desc[:300] + "..." if len(desc) > 300 else desc

    if markets_open:
        action_sme = "HIGH PRIORITY — SME stocks can move 10-20%"
        action_normal = "Review and consider buying"
    else:
        action_sme = "Markets closed — plan to buy at Monday open 🗓"
        action_normal = "Markets closed — plan to buy at Monday open 🗓"

    if is_sme:
        text = (
            f"🔥 <b>SME PRIORITY ALERT</b>\n\n"
            f"📌 <b>Stock</b>     : {symbol} [NSE SME]\n"
            f"🔍 <b>Keyword</b>   : {keyword}\n"
            f"💰 <b>Order Val</b> : {order_value}\n"
            f"📄 <b>Detail</b>    : {desc_truncated}\n"
            f"🕐 <b>Time</b>      : {timestamp}\n"
            f"⚡ <b>Action</b>    : {action_sme}"
        )
    else:
        text = (
            f"🚨 <b>ORDER WIN ALERT</b>\n\n"
            f"📌 <b>Stock</b>     : {symbol}\n"
            f"🔍 <b>Keyword</b>   : {keyword}\n"
            f"💰 <b>Order Val</b> : {order_value}\n"
            f"📄 <b>Detail</b>    : {desc_truncated}\n"
            f"🕐 <b>Time</b>      : {timestamp}\n"
            f"📈 <b>Action</b>    : {action_normal}"
        )
    return send_telegram(text)


def send_market_open_telegram(total: int, smallcap: int, sme: int) -> bool:
    text = (
        f"🟢 <b>Market Open.</b> NSE Alert Bot is watching <b>{total}</b> symbols.\n"
        f"Smallcap: {smallcap} | SME: {sme} | Scanning every 5 minutes."
    )
    return send_telegram(text)


def send_market_close_telegram(alert_count: int, symbols: list) -> bool:
    if alert_count == 0:
        text = "📊 <b>Market Closed.</b> No order wins detected today."
    else:
        sym_list = ", ".join(symbols) if symbols else "—"
        text = (
            f"📊 <b>Market Closed.</b> Today's Alerts: <b>{alert_count}</b> signals fired.\n"
            f"Stocks triggered: {sym_list}"
        )
    return send_telegram(text)


def send_watchlist_warning_telegram(last_date: str) -> bool:
    text = (
        f"⚠️ Watchlist refresh failed. "
        f"Using cached list from {last_date}."
    )
    return send_telegram(text)


def send_error_telegram(message: str) -> bool:
    text = f"⚠️ <b>NSE Alert Bot:</b> {message}"
    return send_telegram(text)


def send_scan_failure_telegram() -> bool:
    return send_error_telegram(
        "3 consecutive scan failures. Check Mac Mini."
    )


def send_boot_telegram(total: int, smallcap: int, sme: int) -> bool:
    text = (
        f"🤖 <b>NSE Alert Bot started.</b> "
        f"Watching <b>{total}</b> symbols "
        f"(Smallcap: {smallcap} | SME: {sme})"
    )
    return send_telegram(text)


def send_api_schema_warning_telegram() -> bool:
    return send_error_telegram(
        "API schema may have changed — manual check needed."
    )


# ── Channel 2: macOS Desktop Notification ────────────────────────────────────

def send_desktop_notification(symbol: str, keyword: str,
                               order_value: str, is_sme: bool = False) -> None:
    """Fire a macOS native popup via osascript (no extra packages needed)."""
    prefix = "🔥 SME PRIORITY — " if is_sme else ""
    title = f"{symbol} — ORDER WIN"
    message = f"{prefix}{keyword} | {order_value}"
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(
            ["osascript", "-e", script],
            timeout=5,
            check=False,
            capture_output=True,
        )
    except Exception as e:
        logger.warning(f"Desktop notification failed: {e}")


# ── Channel 3: Terminal + scan_log.txt ───────────────────────────────────────

def log_scan_cycle(scan_number: int, announcement_count: int,
                   alert_count: int) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"[{ts}] Scan #{scan_number} | "
        f"Announcements: {announcement_count} | "
        f"Alerts: {alert_count}"
    )
    logger.info(msg)


def log_alert(symbol: str, keyword: str, order_value: str,
              is_sme: bool = False) -> None:
    prefix = "[SME PRIORITY] " if is_sme else ""
    logger.info(
        f"ALERT FIRED: {prefix}{symbol} | keyword={keyword} | value={order_value}"
    )


# ── Unified fire_alert (all 3 channels) ──────────────────────────────────────

def fire_alert(symbol: str, keyword: str, order_value: str,
               desc: str, timestamp: str, is_sme: bool = False,
               markets_open: bool = True) -> None:
    """Fire all three notification channels for a detected order win."""
    log_alert(symbol, keyword, order_value, is_sme)
    send_alert_telegram(symbol, keyword, order_value, desc, timestamp, is_sme, markets_open)
    send_desktop_notification(symbol, keyword, order_value, is_sme)
