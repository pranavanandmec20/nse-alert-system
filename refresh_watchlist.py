#!/usr/bin/env python3
"""
refresh_watchlist.py — Daily watchlist auto-updater.

Scheduled via cron at 08:45 IST every weekday:
  45 8 * * 1-5 python3 ~/nse_alert_system/refresh_watchlist.py

Downloads:
  1. Nifty Smallcap 250 CSV  → watchlist_smallcap.csv
  2. NSE SME announcements   → watchlist_sme.csv  (symbol set from SME API)
"""

import os
import sys
import json
import time
import logging
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SMALLCAP_CSV = BASE_DIR / "watchlist_smallcap.csv"
SME_CSV = BASE_DIR / "watchlist_sme.csv"
META_FILE = BASE_DIR / "watchlist_meta.json"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WatchlistRefresh")

# ── URLs ──────────────────────────────────────────────────────────────────────
# NSE equity-stockIndices API — returns live Nifty Smallcap 250 constituents
SMALLCAP_API_URL = (
    "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20SMALLCAP%20250"
)
NSE_SME_API_URL = (
    "https://www.nseindia.com/api/corporate-announcements?index=sme"
)
NSE_HOME = "https://www.nseindia.com"

HEADERS_NSE = {
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_meta() -> dict:
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_meta(meta: dict) -> None:
    META_FILE.write_text(json.dumps(meta, indent=2))


def _send_telegram_warning(message: str) -> None:
    """Best-effort Telegram warning — never block on failure."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass


# ── Smallcap 250 Downloader ───────────────────────────────────────────────────

def refresh_smallcap() -> int:
    """Fetch Nifty Smallcap 250 via NSE equity-stockIndices API. Returns symbol count."""
    meta = _load_meta()
    try:
        logger.info("Fetching Nifty Smallcap 250 from NSE API...")
        session = requests.Session()
        session.get(NSE_HOME, headers=HEADERS_NSE, timeout=15)
        time.sleep(1)

        resp = session.get(SMALLCAP_API_URL, headers=HEADERS_NSE, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("data", [])
        # Filter out the index row itself (symbol == "NIFTY SMALLCAP 250")
        symbols = sorted(set(
            item.get("symbol", "").strip().upper()
            for item in items
            if item.get("symbol", "").strip().upper() not in ("NIFTY SMALLCAP 250", "")
        ))

        if len(symbols) < 100:
            raise ValueError(f"Suspiciously few symbols returned: {len(symbols)}")

        out_df = pd.DataFrame({"Symbol": symbols})
        out_df.to_csv(SMALLCAP_CSV, index=False)

        meta["smallcap_last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta["smallcap_count"] = len(symbols)
        _save_meta(meta)

        logger.info(f"Smallcap watchlist updated: {len(symbols)} symbols.")
        return len(symbols)

    except Exception as e:
        logger.error(f"Smallcap refresh failed: {e}")
        last_date = meta.get("smallcap_last_updated", "unknown date")
        _send_telegram_warning(
            f"⚠️ Watchlist refresh failed (Smallcap 250). "
            f"Using cached list from {last_date}."
        )
        if SMALLCAP_CSV.exists():
            try:
                cached = pd.read_csv(SMALLCAP_CSV)
                return len(cached)
            except Exception:
                pass
        return 0


# ── SME Watchlist Builder ─────────────────────────────────────────────────────

def refresh_sme() -> int:
    """
    Pull unique symbols from NSE SME announcement API.
    Returns symbol count or 0 on failure.
    """
    meta = _load_meta()
    try:
        logger.info("Fetching NSE SME symbol list from announcements API...")
        session = requests.Session()
        # Seed cookies
        session.get(NSE_HOME, headers=HEADERS_NSE, timeout=15)
        time.sleep(1)

        resp = session.get(NSE_SME_API_URL, headers=HEADERS_NSE, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # API returns list directly or nested under a key
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", data.get("announcements", []))
        else:
            items = []

        symbols = sorted(set(
            item.get("symbol", "").strip().upper()
            for item in items
            if item.get("symbol", "").strip()
        ))

        if not symbols:
            raise ValueError("No SME symbols extracted from API response.")

        out_df = pd.DataFrame({"Symbol": symbols})
        out_df.to_csv(SME_CSV, index=False)

        meta["sme_last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta["sme_count"] = len(symbols)
        _save_meta(meta)

        logger.info(f"SME watchlist updated: {len(symbols)} symbols.")
        return len(symbols)

    except Exception as e:
        logger.error(f"SME refresh failed: {e}")
        last_date = meta.get("sme_last_updated", "unknown date")
        _send_telegram_warning(
            f"⚠️ Watchlist refresh failed (NSE SME). "
            f"Using cached list from {last_date}."
        )
        if SME_CSV.exists():
            try:
                cached = pd.read_csv(SME_CSV)
                return len(cached)
            except Exception:
                pass
        return 0


# ── Public API ────────────────────────────────────────────────────────────────

def load_watchlists() -> tuple[set, set]:
    """
    Load both CSVs and return (smallcap_symbols, sme_symbols).
    Each is a set of uppercase symbol strings.
    """
    def _load_csv(path: Path) -> set:
        if not path.exists():
            return set()
        try:
            df = pd.read_csv(path)
            sym_col = next(
                (c for c in df.columns if "symbol" in c.lower()), None
            )
            if sym_col:
                return set(df[sym_col].dropna().str.strip().str.upper())
        except Exception:
            pass
        return set()

    return _load_csv(SMALLCAP_CSV), _load_csv(SME_CSV)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger.info("=== Watchlist Refresh Started ===")
    sc_count = refresh_smallcap()
    sme_count = refresh_sme()
    total = sc_count + sme_count
    logger.info(
        f"=== Refresh Complete: Smallcap={sc_count} | SME={sme_count} | Total={total} ==="
    )


if __name__ == "__main__":
    main()
