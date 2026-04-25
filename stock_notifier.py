import argparse
import json
import os
import re
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


CONFIG_PATH = "monitors.json"
STATE_PATH = ".stock_state.json"
STATE_BLOB_CONTAINER = "stock-notifier-state"
STATE_BLOB_NAME = "stock_state.json"
EXAMPLE_MONITORS = [
    {
        "name": "Myntra product",
        "url": "https://www.myntra.com/paste-your-product-link-here",
        "size": "M",
    }
]


@dataclass
class Monitor:
    name: str
    url: str
    size: str


@dataclass
class StockResult:
    in_stock: bool
    reason: str
    product_title: Optional[str] = None


def read_monitors(path: str) -> List[Monitor]:
    if not os.path.exists(path):
        write_example_monitors(path)
        raise SystemExit(
            f"Created {path}. Edit it with your Myntra product URL and size, then run the script again."
        )

    with open(path, "r", encoding="utf-8") as file:
        raw_monitors = json.load(file)

    monitors = []
    for item in raw_monitors:
        url = str(item["url"]).strip()
        size = str(item["size"]).strip()

        if "paste-your-product-link-here" in url or not url.startswith("https://"):
            raise SystemExit(f"Update the product URL in {path} before running the monitor.")

        if not size:
            raise SystemExit(f"Update the size in {path} before running the monitor.")

        monitors.append(
            Monitor(
                name=str(item.get("name") or item.get("url")),
                url=url,
                size=size,
            )
        )
    return monitors


def read_monitors_from_env() -> Optional[List[Monitor]]:
    raw_value = os.environ.get("MONITORS_JSON")
    if not raw_value:
        return None

    raw_monitors = json.loads(raw_value)
    monitors = []
    for item in raw_monitors:
        monitors.append(
            Monitor(
                name=str(item.get("name") or item.get("url")),
                url=str(item["url"]).strip(),
                size=str(item["size"]).strip(),
            )
        )
    return monitors


def load_monitors(path: str = CONFIG_PATH) -> List[Monitor]:
    return read_monitors_from_env() or read_monitors(path)


def write_example_monitors(path: str) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(EXAMPLE_MONITORS, file, indent=2)
        file.write("\n")


def read_state(path: str) -> Dict[str, bool]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_state(path: str, state: Dict[str, bool]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)


def get_blob_state_client():
    connection_string = os.environ.get("STOCK_STATE_CONNECTION_STRING") or os.environ.get(
        "AzureWebJobsStorage"
    )
    if not connection_string:
        return None

    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        return None

    container_name = os.environ.get("STOCK_STATE_CONTAINER", STATE_BLOB_CONTAINER)
    blob_name = os.environ.get("STOCK_STATE_BLOB", STATE_BLOB_NAME)
    service = BlobServiceClient.from_connection_string(connection_string)
    container = service.get_container_client(container_name)
    try:
        container.create_container()
    except Exception:
        pass
    return container.get_blob_client(blob_name)


def use_blob_state() -> bool:
    if os.environ.get("USE_BLOB_STATE"):
        return str_to_bool(os.environ.get("USE_BLOB_STATE"), default=True)
    return bool(os.environ.get("AzureWebJobsStorage"))


def read_state_store(path: str = STATE_PATH) -> Dict[str, bool]:
    if not use_blob_state():
        return read_state(path)

    blob = get_blob_state_client()
    if blob is None:
        return read_state(path)

    try:
        data = blob.download_blob().readall().decode("utf-8")
        return json.loads(data)
    except Exception:
        return {}


def write_state_store(state: Dict[str, bool], path: str = STATE_PATH) -> None:
    if not use_blob_state():
        write_state(path, state)
        return

    blob = get_blob_state_client()
    if blob is None:
        write_state(path, state)
        return

    blob.upload_blob(json.dumps(state, indent=2, sort_keys=True), overwrite=True)


def state_key(monitor: Monitor) -> str:
    return f"{monitor.url}::{monitor.size.upper()}"


def str_to_bool(value: str, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def send_email(monitor: Monitor, result: StockResult) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ.get("EMAIL_FROM", username)
    email_to = os.environ["EMAIL_TO"]

    subject = f"Size {monitor.size} is back in stock: {monitor.name}"
    body = "\n".join(
        [
            f"Good news: size {monitor.size} looks available.",
            "",
            f"Product: {result.product_title or monitor.name}",
            f"Monitor: {monitor.name}",
            f"URL: {monitor.url}",
            f"Signal: {result.reason}",
        ]
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_from
    message["To"] = email_to
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def extract_product_id(url: str) -> Optional[str]:
    match = re.search(r"/(\d+)/buy(?:\?|$)", url)
    if match:
        return match.group(1)

    matches = re.findall(r"\d{6,}", url)
    return matches[-1] if matches else None


def fetch_myntra_product(product_id: str) -> Optional[Dict[str, Any]]:
    api_url = f"https://www.myntra.com/gateway/v2/product/{product_id}"
    request = Request(
        api_url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.myntra.com/",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        print(f"Myntra API check failed: {exc}")
        return None


def fetch_myntra_html(url: str) -> Optional[str]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, URLError) as exc:
        print(f"Myntra HTML check failed: {exc}")
        return None


def extract_myntra_state(html: str) -> Optional[Dict[str, Any]]:
    marker = "window.__myx = "
    start = html.find(marker)
    if start == -1:
        return None

    decoder = json.JSONDecoder()
    try:
        state, _ = decoder.raw_decode(html[start + len(marker) :])
        return state
    except json.JSONDecodeError as exc:
        print(f"Myntra embedded data parse failed: {exc}")
        return None


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def text_matches_size(value: Any, size: str) -> bool:
    if value is None:
        return False

    text = str(value).strip().upper()
    if text == size:
        return True

    tokens = {token.strip(".,:;()[]{}") for token in text.split()}
    return size in tokens


def read_bool_stock_signal(item: Dict[str, Any]) -> Optional[bool]:
    for key in ["available", "isAvailable", "inStock", "isInStock", "inventoryAvailable"]:
        if key in item and isinstance(item[key], bool):
            return item[key]

    for key in ["inventory", "inventoryCount", "quantity", "availableQuantity", "qty"]:
        if key in item:
            try:
                return int(item[key]) > 0
            except (TypeError, ValueError):
                pass

    for key in ["status", "availability", "stockStatus"]:
        if key in item:
            text = str(item[key]).lower()
            if any(word in text for word in ["in stock", "available"]):
                return True
            if any(word in text for word in ["out", "sold", "unavailable"]):
                return False

    return None


def check_myntra_api_stock(monitor: Monitor) -> Optional[StockResult]:
    product_id = extract_product_id(monitor.url)
    if not product_id:
        return None

    data = fetch_myntra_product(product_id)
    if not data:
        return None

    size = monitor.size.strip().upper()
    title = None
    for key in ["productName", "name", "title"]:
        if isinstance(data.get(key), str) and data[key].strip():
            title = data[key].strip()
            break

    for item in iter_dicts(data):
        size_fields = ["size", "label", "value", "name", "displaySize", "skuSize"]
        if not any(text_matches_size(item.get(field), size) for field in size_fields):
            continue

        signal = read_bool_stock_signal(item)
        if signal is True:
            return StockResult(True, f"API reports size {monitor.size} is available", title)
        if signal is False:
            return StockResult(False, f"API reports size {monitor.size} is not available", title)

    return StockResult(False, f"API did not find an available stock signal for size {monitor.size}", title)


def check_myntra_html_stock(monitor: Monitor) -> Optional[StockResult]:
    html = fetch_myntra_html(monitor.url)
    if not html:
        return None

    state = extract_myntra_state(html)
    if not state:
        return None

    product = state.get("pdpData") or {}
    title = product.get("name")
    size = monitor.size.strip().upper()

    for item in product.get("sizes") or []:
        label = item.get("label") or item.get("size") or item.get("value")
        if not text_matches_size(label, size):
            continue

        available = bool(item.get("available"))
        if available:
            return StockResult(True, f"HTML data reports size {monitor.size} is available", title)

        return StockResult(False, f"HTML data reports size {monitor.size} is not available", title)

    flags = product.get("flags") or {}
    if flags.get("outOfStock") is True:
        return StockResult(False, "HTML data reports the product is out of stock", title)

    return StockResult(False, f"HTML data did not find size {monitor.size}", title)


def open_product_page(page, url: str) -> None:
    last_error = None
    for attempt in range(1, 4):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return
        except Exception as exc:
            last_error = exc
            print(f"Page load attempt {attempt} failed: {exc}")
            time.sleep(3 * attempt)

    raise last_error


def check_myntra_stock(page, monitor: Monitor) -> StockResult:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    open_product_page(page, monitor.url)

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass

    close_buttons = [
        "button:has-text('✕')",
        "button:has-text('X')",
        "[aria-label='Close']",
        ".modal-close",
    ]
    for selector in close_buttons:
        try:
            if page.locator(selector).first.is_visible(timeout=1000):
                page.locator(selector).first.click(timeout=1000)
                break
        except PlaywrightTimeoutError:
            continue

    title = None
    for selector in [".pdp-title", "h1", "[class*='title']"]:
        try:
            text = page.locator(selector).first.inner_text(timeout=2000).strip()
            if text:
                title = text
                break
        except PlaywrightTimeoutError:
            continue

    size = monitor.size.strip().upper()
    candidates = page.locator(
        ".size-buttons-size-button, "
        ".size-buttons-unified-size, "
        "[class*='size-buttons'], "
        "button, "
        "li"
    )

    count = candidates.count()
    matched_texts = []

    for index in range(count):
        element = candidates.nth(index)
        try:
            text = " ".join(element.inner_text(timeout=1000).split()).strip()
        except PlaywrightTimeoutError:
            continue

        normalized = text.upper()
        tokens = {token.strip(".,:;()[]{}") for token in normalized.split()}
        if normalized != size and size not in tokens:
            continue

        matched_texts.append(text)
        classes = (element.get_attribute("class") or "").lower()
        aria_disabled = (element.get_attribute("aria-disabled") or "").lower()
        disabled = element.get_attribute("disabled") is not None
        unavailable_words = ["disabled", "unavailable", "not-available", "soldout", "sold-out"]

        if disabled or aria_disabled == "true" or any(word in classes for word in unavailable_words):
            return StockResult(False, f"matched size element is disabled: {text}", title)

        return StockResult(True, f"matched available size element: {text}", title)

    page_text = page.locator("body").inner_text(timeout=5000).upper()
    if size in page_text and "ADD TO BAG" in page_text:
        return StockResult(True, "size text and add-to-bag text were visible", title)

    if matched_texts:
        return StockResult(False, f"size matched but no available signal: {matched_texts[0]}", title)

    return StockResult(False, f"size {monitor.size} was not found on the page", title)


def run_check(monitors: List[Monitor], send_notifications: bool) -> None:
    state = read_state_store(STATE_PATH)
    headless = str_to_bool(os.environ.get("HEADLESS", "true"))
    browser_fallback = str_to_bool(os.environ.get("BROWSER_FALLBACK", "false"), default=False)
    playwright = None
    browser = None
    context = None

    try:
        for monitor in monitors:
            key = state_key(monitor)
            was_in_stock = bool(state.get(key, False))

            try:
                result = check_myntra_html_stock(monitor)

                if result is None:
                    result = check_myntra_api_stock(monitor)

                if result is None and browser_fallback:
                    if browser is None:
                        from playwright.sync_api import sync_playwright

                        playwright = sync_playwright().start()
                        browser = playwright.chromium.launch(headless=headless)
                        context = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                            ),
                            extra_http_headers={
                                "Accept-Language": "en-IN,en;q=0.9",
                                "Upgrade-Insecure-Requests": "1",
                            },
                            locale="en-IN",
                            timezone_id="Asia/Kolkata",
                            viewport={"width": 1366, "height": 900},
                        )

                    page = context.new_page()
                    try:
                        result = check_myntra_stock(page, monitor)
                    finally:
                        page.close()

                if result is None:
                    result = StockResult(
                        False,
                        "could not read Myntra product data; set BROWSER_FALLBACK=true to try browser scraping",
                    )

                print(f"[{monitor.name}] size {monitor.size}: {result.reason}")

                if result.in_stock and not was_in_stock and send_notifications:
                    send_email(monitor, result)
                    print(f"[{monitor.name}] email notification sent")

                state[key] = result.in_stock
            except Exception as exc:
                print(f"[{monitor.name}] check failed: {exc}")

        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
    finally:
        if playwright is not None:
            playwright.stop()

    write_state_store(state, STATE_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="Email when a Myntra product size is back in stock.")
    parser.add_argument("--once", action="store_true", help="Run one check and exit.")
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Check stock without sending notification emails.",
    )
    parser.add_argument(
        "--config",
        default=CONFIG_PATH,
        help=f"Path to monitor config. Defaults to {CONFIG_PATH}.",
    )
    args = parser.parse_args()

    load_dotenv()
    monitors = load_monitors(args.config)
    interval = int(os.environ.get("CHECK_INTERVAL_SECONDS", "900"))

    while True:
        run_check(monitors, send_notifications=not args.no_email)
        if args.once:
            break
        print(f"Sleeping for {interval} seconds")
        time.sleep(interval)


if __name__ == "__main__":
    main()
