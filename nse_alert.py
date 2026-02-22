#!/usr/bin/env python3
"""
nse_alert.py — NSE Small-Cap & SME Order Win Alert System
Main monitoring script. Run persistently via pm2.

Weekdays : 09:00–16:00 IST, scan every 5 minutes.
Weekends : 08:00–20:00 IST, scan every 30 minutes.
"""

import os
import sys
import json
import time
import hashlib
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# ── Load env and local modules ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))
from notifier import (
    logger,
    fire_alert,
    log_scan_cycle,
    send_telegram,
    send_boot_telegram,
    send_market_open_telegram,
    send_market_close_telegram,
    send_scan_failure_telegram,
    send_api_schema_warning_telegram,
)
from xbrl_parser import extract_order_value
from refresh_watchlist import load_watchlists, refresh_smallcap, refresh_sme

# ── Constants ─────────────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")
SCAN_INTERVAL_SECS = 300          # 5 minutes (weekdays)
WEEKEND_SCAN_INTERVAL_SECS = 1800 # 30 minutes (weekends)
SESSION_REFRESH_SECS = 1800       # 30 minutes
MAX_CONSECUTIVE_FAILURES = 3
ALERTS_LOG = BASE_DIR / "alerts_log.json"

MARKET_OPEN_HOUR = 9
MARKET_CLOSE_HOUR = 16
WEEKEND_SCAN_START_HOUR = 8       # Weekend scanning: 08:00 IST
WEEKEND_SCAN_END_HOUR = 20        # Weekend scanning: 20:00 IST

NSE_HOME = "https://www.nseindia.com"
NSE_SMALLCAP_API = "https://www.nseindia.com/api/corporate-announcements"
NSE_SME_API = "https://www.nseindia.com/api/corporate-announcements?index=sme"

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "referer": (
        "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    ),
}

# Keywords that signal an order win announcement
ORDER_KEYWORDS = [
    "award",
    "order",
    "contract",
    "bagged",
    "l1",
    " won",
    "letter of intent",
    "loi",
    "procurement",
    "supply",
    "empanelled",
    "work order",
    "purchase order",
    "secured",
    "received order",
    "new order",
    "order inflow",
]


# ── Alert deduplication ───────────────────────────────────────────────────────

def _load_alerts_log() -> dict:
    if ALERTS_LOG.exists():
        try:
            return json.loads(ALERTS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_alerts_log(log: dict) -> None:
    ALERTS_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


def _alert_key(symbol: str, desc: str) -> str:
    today = date.today().isoformat()
    h = hashlib.md5(desc.encode("utf-8")).hexdigest()[:8]
    return f"{symbol}_{today}_{h}"


def _is_duplicate(log: dict, key: str) -> bool:
    return key in log


def _mark_seen(log: dict, key: str, symbol: str, keyword: str) -> None:
    log[key] = {
        "symbol": symbol,
        "keyword": keyword,
        "fired_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    }


# ── NSE Session Manager ───────────────────────────────────────────────────────

class NSESession:
    """Manages a requests.Session with NSE cookie/header handling."""

    def __init__(self):
        self._session = None
        self._last_init: datetime = None

    def _init(self):
        logger.info("Initialising NSE session...")
        s = requests.Session()
        try:
            s.get(NSE_HOME, headers=NSE_HEADERS, timeout=15)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"NSE home page seed failed: {e}")
        self._session = s
        self._last_init = datetime.now()
        logger.info("NSE session ready.")

    def get(self, url: str, **kwargs):
        if self._session is None or self._session_stale():
            self._init()
        kwargs.setdefault("headers", NSE_HEADERS)
        kwargs.setdefault("timeout", 15)
        return self._session.get(url, **kwargs)

    def _session_stale(self) -> bool:
        if self._last_init is None:
            return True
        return (datetime.now() - self._last_init).total_seconds() > SESSION_REFRESH_SECS


# ── Announcement Fetcher ──────────────────────────────────────────────────────

def fetch_announcements(session: NSESession) -> list[dict]:
    """
    Fetch both smallcap and SME announcement feeds.
    Returns a list of dicts, each tagged with 'is_sme'.
    """
    results = []
    endpoints = [
        (NSE_SMALLCAP_API, False),
        (NSE_SME_API, True),
    ]
    for url, is_sme in endpoints:
        try:
            resp = session.get(url)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                # Try common key names
                items = data.get("data", data.get("announcements", []))
                if not isinstance(items, list):
                    # Unexpected schema
                    logger.warning(f"Unexpected API schema from {url}: {list(data.keys())}")
                    send_api_schema_warning_telegram()
                    items = []
            else:
                items = []

            for item in items:
                item["_is_sme"] = is_sme
            results.extend(items)

        except requests.exceptions.RequestException as e:
            label = "SME" if is_sme else "Smallcap"
            logger.error(f"Fetch failed ({label}): {e}")
        except ValueError as e:
            logger.error(f"JSON parse error from {url}: {e}")

    return results


# ── Signal Detector ───────────────────────────────────────────────────────────

def detect_signal(item: dict, watchlist: set) -> tuple[bool, str]:
    """
    Returns (True, matched_keyword) if this announcement is an order win
    for a watched symbol, else (False, '').
    """
    symbol = (item.get("symbol") or item.get("scripCode") or "").strip().upper()
    if symbol not in watchlist:
        return False, ""

    desc = (item.get("desc") or item.get("subject") or item.get("description") or "").lower()
    for kw in ORDER_KEYWORDS:
        if kw in desc:
            return True, kw

    return False, ""


# ── Watchlist State ───────────────────────────────────────────────────────────

class WatchlistState:
    def __init__(self):
        self.smallcap: set = set()
        self.sme: set = set()
        self.combined: set = set()

    def refresh(self):
        self.smallcap, self.sme = load_watchlists()
        self.combined = self.smallcap | self.sme
        logger.info(
            f"Watchlist loaded: Smallcap={len(self.smallcap)} | "
            f"SME={len(self.sme)} | Total={len(self.combined)}"
        )

    def total(self) -> int:
        return len(self.combined)

    def is_sme(self, symbol: str) -> bool:
        return symbol in self.sme


# ── Time Gate Helpers ─────────────────────────────────────────────────────────

def is_market_hours() -> bool:
    """Weekday 09:00–16:00 IST."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR


def is_weekend_scan_hours() -> bool:
    """Saturday/Sunday 08:00–20:00 IST."""
    now = datetime.now(IST)
    if now.weekday() < 5:
        return False
    return WEEKEND_SCAN_START_HOUR <= now.hour < WEEKEND_SCAN_END_HOUR


def is_active_scan_time() -> bool:
    return is_market_hours() or is_weekend_scan_hours()


def ist_now_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def seconds_until_market_close() -> int:
    now = datetime.now(IST)
    target = now.replace(hour=MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
    return max(0, int((target - now).total_seconds()))


def seconds_until_weekend_scan_end() -> int:
    now = datetime.now(IST)
    target = now.replace(hour=WEEKEND_SCAN_END_HOUR, minute=0, second=0, microsecond=0)
    return max(0, int((target - now).total_seconds()))


# ── Main Scan Loop ────────────────────────────────────────────────────────────

def run():
    logger.info("=" * 60)
    logger.info("NSE Alert Bot — Starting up")
    logger.info("=" * 60)

    watchlist = WatchlistState()

    # Try to load existing watchlists; if empty, attempt a fresh download
    watchlist.refresh()
    if watchlist.total() == 0:
        logger.warning("Watchlists empty — attempting initial download...")
        refresh_smallcap()
        refresh_sme()
        watchlist.refresh()

    # Send boot message
    send_boot_telegram(
        watchlist.total(),
        len(watchlist.smallcap),
        len(watchlist.sme),
    )

    session = NSESession()
    alerts_log = _load_alerts_log()
    scan_number = 0
    consecutive_failures = 0
    today_alerts: list[str] = []
    last_market_open_date = None
    last_market_close_date = None
    market_was_open = False

    while True:
        now_ist = datetime.now(IST)
        today_date = now_ist.date()
        is_weekend = now_ist.weekday() >= 5

        # ── Weekday: market open signal ───────────────────────────────────
        if is_market_hours() and last_market_open_date != today_date:
            last_market_open_date = today_date
            today_alerts = []
            watchlist.refresh()
            send_market_open_telegram(
                watchlist.total(),
                len(watchlist.smallcap),
                len(watchlist.sme),
            )
            market_was_open = True

        # ── Weekday: market close summary ─────────────────────────────────
        if not is_weekend and not is_market_hours():
            if market_was_open and last_market_close_date != today_date:
                last_market_close_date = today_date
                market_was_open = False
                send_market_close_telegram(len(today_alerts), today_alerts)

        # ── Not an active scan window — sleep and loop ────────────────────
        if not is_active_scan_time():
            logger.info(f"Inactive scan window ({ist_now_str()}). Sleeping 60s...")
            time.sleep(60)
            continue

        # ── Scan (weekday market hours OR weekend window) ─────────────────
        scan_number += 1
        alerts_this_cycle = 0
        announcements = []

        try:
            announcements = fetch_announcements(session)
            if not announcements and scan_number == 1:
                logger.warning("First scan returned zero announcements — check API connectivity.")

            for item in announcements:
                is_sme_item = item.get("_is_sme", False)

                matched, keyword = detect_signal(item, watchlist.combined)
                if not matched:
                    continue

                symbol = (
                    item.get("symbol") or item.get("scripCode") or ""
                ).strip().upper()
                desc = (
                    item.get("desc") or item.get("subject") or
                    item.get("description") or ""
                )
                attachment = item.get("attchmntFile") or item.get("attachment") or ""

                # Deduplication
                key = _alert_key(symbol, desc)
                if _is_duplicate(alerts_log, key):
                    continue

                # Determine if truly SME (by watchlist membership)
                is_sme = watchlist.is_sme(symbol) or is_sme_item

                # Extract order value from XBRL
                order_value = extract_order_value(attachment, session._session)

                timestamp = ist_now_str()

                # Fire all channels — pass markets_open flag
                fire_alert(
                    symbol, keyword, order_value, desc, timestamp,
                    is_sme=is_sme, markets_open=not is_weekend,
                )

                # Mark seen
                _mark_seen(alerts_log, key, symbol, keyword)
                _save_alerts_log(alerts_log)

                if symbol not in today_alerts:
                    today_alerts.append(symbol)

                alerts_this_cycle += 1

            consecutive_failures = 0

        except Exception as e:
            consecutive_failures += 1
            logger.error(
                f"Scan #{scan_number} failed (consecutive={consecutive_failures}): {e}"
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                send_scan_failure_telegram()
                consecutive_failures = 0

        log_scan_cycle(scan_number, len(announcements), alerts_this_cycle)

        # ── Sleep until next scan ─────────────────────────────────────────
        if is_weekend:
            sleep_time = min(
                WEEKEND_SCAN_INTERVAL_SECS,
                seconds_until_weekend_scan_end() + 5,
            )
        else:
            sleep_time = min(
                SCAN_INTERVAL_SECS,
                seconds_until_market_close() + 5,
            )
        if sleep_time > 0:
            time.sleep(sleep_time)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("NSE Alert Bot stopped by user (KeyboardInterrupt).")
        send_telegram("🔴 <b>NSE Alert Bot manually stopped.</b>")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        send_telegram(f"🔴 <b>NSE Alert Bot crashed:</b> {e}")
        sys.exit(1)
