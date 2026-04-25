# Myntra Size Stock Notifier

This is a small Python monitor that checks whether a selected Myntra size looks available and emails you when it comes back in stock.

It reads Myntra's embedded product data from the product page HTML. Scraping may be restricted by a site's terms or anti-bot systems, so keep the polling interval polite and use this only for personal notifications.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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

## Run on Azure every 15 minutes

This repo is ready to deploy as an Azure Functions app. The timer trigger is in `function_app.py` and runs every 15 minutes with this schedule:

```text
0 */15 * * * *
```

Create a Python Azure Function App, then add these app settings in Azure:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-google-app-password
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=destination-email@gmail.com
MONITORS_JSON=[{"name":"Myntra jeans","url":"https://www.myntra.com/jeans/snitch/snitch-men-straight-fit-mid-rise-jeans/38525890/buy","size":"30"}]
USE_BLOB_STATE=true
BROWSER_FALLBACK=false
```

`AzureWebJobsStorage` is created by Azure Functions. The notifier uses that storage account to remember whether a size was already in stock, so you do not get the same email every 15 minutes.

### Deploy with Azure Functions Core Tools

Install Azure Functions Core Tools and Azure CLI, then run:

```bash
az login
func azure functionapp publish YOUR_FUNCTION_APP_NAME
```

After deployment, open the Function App in Azure Portal and check **Log stream**. You should see lines like:

```text
[Myntra jeans] size 30: HTML data reports size 30 is not available
```

When it becomes available, the logs should include:

```text
[Myntra jeans] email notification sent
```

## Debugging selectors

The script checks Myntra's product page HTML first, then tries Myntra's product-data endpoint. If that does not work and you want to try browser scraping locally, install Playwright and enable the fallback:

```bash
pip install playwright
python -m playwright install chromium
BROWSER_FALLBACK=true python stock_notifier.py --once
```

If the site layout changes, run the fallback with the browser visible:

```bash
BROWSER_FALLBACK=true HEADLESS=false python stock_notifier.py --once
```

The scraper tries common Myntra size-button patterns and also falls back to text matching, but product pages can change over time.
