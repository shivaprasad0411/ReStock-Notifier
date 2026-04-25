# Myntra Size Stock Notifier

This is a small Python monitor that opens a product page, checks whether a selected size looks available, and emails you when it comes back in stock.

It uses Playwright because many shopping pages render stock state with JavaScript. Scraping may be restricted by a site's terms or anti-bot systems, so keep the polling interval polite and use this only for personal notifications.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
cp monitors.example.json monitors.json
```

Edit `.env` with your SMTP settings and edit `monitors.json` with the Myntra product link and size you want.

For Gmail, use an app password rather than your normal account password.

## Run once

```bash
python stock_notifier.py --once
```

## Run continuously

```bash
python stock_notifier.py
```

By default it checks every 15 minutes. Change `CHECK_INTERVAL_SECONDS` in `.env` if you want a different interval.

## Debugging selectors

The script checks Myntra's product-data endpoint first. If that does not work and you want to try browser scraping, enable the fallback:

```bash
BROWSER_FALLBACK=true python stock_notifier.py --once
```

If the site layout changes, run the fallback with the browser visible:

```bash
BROWSER_FALLBACK=true HEADLESS=false python stock_notifier.py --once
```

The scraper tries common Myntra size-button patterns and also falls back to text matching, but product pages can change over time.
