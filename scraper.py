"""
Dropshipping Arbitrage Scraper
Scrapes Amazon AU + AliExpress, filters $50-$100 products,
calculates 50% ROI eBay resale price, saves to products.json
"""

import os
import json
import time
import logging
import requests
from datetime import date, datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
MIN_PRICE = 50.0
MAX_PRICE = 100.0
ROI_TARGET = 0.50  # 50% profit margin → sell at cost × 1.5

CATEGORIES = {
    "kitchen":   ["kitchen gadgets", "cookware set", "kitchen tools"],
    "pet":       ["pet feeder", "cat litter", "dog bed"],
    "home":      ["home organiser", "smart home device", "home decor"],
    "employee":  ["office desk accessories", "ergonomic keyboard", "laptop stand"],
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def scraper_get(url: str, retries: int = 3) -> requests.Response | None:
    """Fetch a URL via ScraperAPI with retries."""
    if not SCRAPERAPI_KEY:
        log.error("SCRAPERAPI_KEY not set — cannot fetch live data.")
        return None
    proxy_url = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPERAPI_KEY}"
        f"&url={requests.utils.quote(url, safe=':/?=&')}"
        f"&country_code=au"
    )
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(proxy_url, timeout=60)
            if resp.status_code == 200:
                return resp
            log.warning(f"Attempt {attempt}: HTTP {resp.status_code} for {url}")
        except Exception as e:
            log.warning(f"Attempt {attempt}: {e}")
        time.sleep(2 ** attempt)
    return None


def parse_price(text: str) -> float | None:
    """Extract first numeric price from a string like '$64.99' or 'AU $72.50'."""
    import re
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


def calc_ebay(buy: float) -> dict:
    """Return eBay sell price, profit, and ROI for a given buy price."""
    sell = round(buy * (1 + ROI_TARGET), 2)
    profit = round(sell - buy, 2)
    roi = round((profit / buy) * 100, 1)
    return {"ebay_price": sell, "profit": profit, "roi_pct": roi}


# ─── Amazon AU scraper ────────────────────────────────────────────────────────

def scrape_amazon_au(keyword: str, category: str) -> list[dict]:
    """Scrape Amazon AU search results for a keyword."""
    url = f"https://www.amazon.com.au/s?k={requests.utils.quote(keyword)}&language=en_AU"
    log.info(f"[Amazon AU] {keyword}")
    resp = scraper_get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []

    for item in soup.select('[data-component-type="s-search-result"]')[:8]:
        try:
            name_el = item.select_one("h2 .a-text-normal")
            price_whole = item.select_one(".a-price-whole")
            price_frac  = item.select_one(".a-price-fraction")

            if not name_el or not price_whole:
                continue

            name = name_el.get_text(strip=True)
            price_str = price_whole.get_text(strip=True).replace(",", "")
            if price_frac:
                price_str += "." + price_frac.get_text(strip=True)

            price = parse_price(price_str)
            if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            products.append({
                "name": name[:120],
                "source": "Amazon AU",
                "category": category,
                "buy_price": price,
                **calc_ebay(price),
            })
        except Exception as e:
            log.debug(f"Amazon parse error: {e}")
            continue

    log.info(f"  → {len(products)} products found")
    return products


# ─── AliExpress scraper ───────────────────────────────────────────────────────

def scrape_aliexpress(keyword: str, category: str) -> list[dict]:
    """Scrape AliExpress search results for a keyword (AUD price filter)."""
    url = (
        f"https://www.aliexpress.com/wholesale"
        f"?SearchText={requests.utils.quote(keyword)}"
        f"&minPrice=50&maxPrice=100&currency=AUD"
    )
    log.info(f"[AliExpress] {keyword}")
    resp = scraper_get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []

    # AliExpress uses several possible card selectors
    cards = (
        soup.select(".list--gallery--C2f2tvm .item--wrap--B6CFMfh") or
        soup.select("[class*='product-card']") or
        soup.select("[class*='SearchProductCard']")
    )

    for item in cards[:8]:
        try:
            name_el  = item.select_one("[class*='title']") or item.select_one("h3")
            price_el = item.select_one("[class*='price']")

            if not name_el or not price_el:
                continue

            name  = name_el.get_text(strip=True)
            price = parse_price(price_el.get_text(strip=True))

            if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            products.append({
                "name": name[:120],
                "source": "AliExpress",
                "category": category,
                "buy_price": price,
                **calc_ebay(price),
            })
        except Exception as e:
            log.debug(f"AliExpress parse error: {e}")
            continue

    log.info(f"  → {len(products)} products found")
    return products


# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    log.info("=== Arbitrage scraper starting ===")
    all_products: list[dict] = []

    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            all_products.extend(scrape_amazon_au(kw, category))
            time.sleep(1.5)
            all_products.extend(scrape_aliexpress(kw, category))
            time.sleep(1.5)

    # Deduplicate by name similarity (simple prefix match)
    seen: set[str] = set()
    unique = []
    for p in all_products:
        key = p["name"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Filter: only 50%+ ROI (should all qualify, but double-check)
    qualified = [p for p in unique if p["roi_pct"] >= 50]
    qualified.sort(key=lambda x: x["profit"], reverse=True)

    output = {
        "date": date.today().isoformat(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total": len(qualified),
        "products": qualified,
    }

    os.makedirs("data", exist_ok=True)
    path = f"data/products_{date.today().isoformat()}.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)

    # Also write latest.json for the dashboard to read
    with open("data/latest.json", "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"=== Done. {len(qualified)} opportunities saved to {path} ===")


if __name__ == "__main__":
    run()
