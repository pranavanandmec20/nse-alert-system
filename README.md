# NSE Small-Cap & SME Order Win Alert System

Automated Python system that scans NSE corporate announcements every 5 minutes during market hours, detects order win signals for small-cap and SME stocks, and delivers real-time alerts via Telegram and macOS desktop notifications.

## Features

- Monitors **Nifty Smallcap 250** + **NSE SME Platform** stocks (269 symbols)
- Scans every **5 minutes** on weekdays (09:00–16:00 IST)
- Scans every **30 minutes** on weekends (08:00–20:00 IST) for late filings
- Extracts **exact order value in ₹ Crores** from XBRL filings
- **Zero duplicate alerts** via hash-based deduplication
- Runs persistently via **pm2** with macOS sleep prevention (`caffeinate`)
- Auto-refreshes watchlist every morning at 08:45 IST via **launchd**

## Alert Channels

| Channel | Trigger |
|---------|---------|
| 📱 Telegram mobile push | Every order win — highest priority |
| 🖥 macOS desktop popup | Every order win — with Glass sound |
| 📄 `scan_log.txt` | Every scan cycle — full audit trail |

## Alert Format

```
🚨 ORDER WIN ALERT

📌 Stock     : KPIL
🔍 Keyword   : work order
💰 Order Val : ₹245.00 Crores
📄 Detail    : Company received work order from NHAI...
🕐 Time      : 2026-02-24 10:15:30 IST
📈 Action    : Review and consider buying
```

SME stocks get `🔥 SME PRIORITY ALERT` with elevated action message.

## File Structure

```
nse_alert_system/
├── nse_alert.py          # Main monitoring loop
├── refresh_watchlist.py  # Daily watchlist auto-updater
├── xbrl_parser.py        # XBRL order value extractor (5s timeout)
├── notifier.py           # Telegram + macOS + log channels
├── test_telegram.py      # One-time connection tester
├── run_alert.sh          # pm2 wrapper with caffeinate (prevents Mac sleep)
├── .env                  # Credentials — NOT committed (see .gitignore)
└── .gitignore
```

## Setup

### 1. Install dependencies
```bash
pip3 install requests plyer schedule pandas lxml beautifulsoup4 python-dotenv
npm install -g pm2
```

### 2. Configure Telegram
Create a bot via [@BotFather](https://t.me/BotFather) and get your chat ID, then:
```bash
cp .env.example .env   # fill in your token and chat_id
```

`.env` format:
```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 3. Test Telegram connection
```bash
python3 test_telegram.py
```

### 4. Download initial watchlists
```bash
python3 refresh_watchlist.py
```

### 5. Deploy persistently
```bash
pm2 start run_alert.sh --name "nse-alert" --interpreter bash
pm2 save
pm2 startup
```

### 6. Schedule daily watchlist refresh (macOS launchd)
Copy `com.nse.watchlist.refresh.plist` to `~/Library/LaunchAgents/` and load it:
```bash
launchctl load ~/Library/LaunchAgents/com.nse.watchlist.refresh.plist
```

## Monitoring

```bash
pm2 logs nse-alert          # Live logs
pm2 list                    # Health check
tail -f scan_log.txt        # Scan history
cat alerts_log.json         # All alerts fired
```

## Order Win Keywords

`award`, `order`, `contract`, `bagged`, `l1`, `won`, `letter of intent`, `loi`, `procurement`, `supply`, `empanelled`, `work order`, `purchase order`, `secured`, `received order`, `new order`, `order inflow`

## Notes

- `.env` is in `.gitignore` — never committed
- XBRL parsing has a hard 5-second timeout — never blocks alerts
- `caffeinate -i` in `run_alert.sh` prevents Mac Mini from sleeping
- Deduplication key: `{symbol}_{date}_{desc_hash}`
