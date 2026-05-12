"""
Dropshipping Arbitrage Scraper v2
Uses ScraperAPI's Structured Data endpoint (built for Amazon)
+ AliExpress via render=true for JS pages
"""

import os
import json
import time
import logging
import requests
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
MIN_PRICE = 50.0
MAX_PRICE = 100.0
ROI_TARGET = 0.50

CATEGORIES = {
    "kitchen":  ["kitchen gadgets", "cookware set", "silicone baking", "coffee maker"],
    "pet":      ["automatic pet feeder", "cat litter box", "dog bed orthopedic"],
    "home":     ["smart home device", "cordless vacuum", "led smart bulb"],
    "employee": ["ergonomic chair cushion", "laptop stand aluminium", "usb c hub"],
}


def calc_ebay(buy: float) -> dict:
    sell   = round(buy * 1.5, 2)
    profit = round(sell - buy, 2)
    roi    = round((profit / buy) * 100, 1)
    return {"ebay_price": sell, "profit": profit, "roi_pct": roi}


def scrape_amazon_structured(keyword: str, category: str) -> list[dict]:
    if not SCRAPERAPI_KEY:
        log.error("SCRAPERAPI_KEY not set")
        return []

    url = "https://api.scraperapi.com/structured/amazon/search"
    params = {
        "api_key": SCRAPERAPI_KEY,
        "query":   keyword,
        "country": "au",
    }

    log.info(f"[Amazon AU] {keyword}")
    try:
        resp = requests.get(url, params=params, timeout=60)
        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code}")
            return []

        data    = resp.json()
        results = data.get("results", []) or data.get("organic_results", [])
        products = []

        for item in results[:10]:
            try:
                import re
                name      = item.get("name") or item.get("title", "")
                price_raw = item.get("price") or item.get("price_string") or ""
                if isinstance(price_raw, str):
                    m = re.search(r"[\d,]+\.?\d*", price_raw.replace(",", ""))
                    price = float(m.group()) if m else None
                elif isinstance(price_raw, (int, float)):
                    price = float(price_raw)
                else:
                    price = None

                if not name or price is None:
                    continue
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue

                products.append({
                    "name":      name[:120],
                    "source":    "Amazon AU",
                    "category":  category,
                    "buy_price": price,
                    **calc_ebay(price),
                })
            except Exception as e:
                log.debug(f"  parse error: {e}")
                continue

        log.info(f"  -> {len(products)} products")
        return products

    except Exception as e:
        log.warning(f"  request error: {e}")
        return []


def scrape_aliexpress(keyword: str, category: str) -> list[dict]:
    if not SCRAPERAPI_KEY:
        return []

    import re
    from bs4 import BeautifulSoup

    search_url = (
        f"https://www.aliexpress.com/wholesale"
        f"?SearchText={requests.utils.quote(keyword)}"
        f"&minPrice=50&maxPrice=100&currencyCode=AUD"
    )
    proxy = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPERAPI_KEY}"
        f"&render=true"
        f"&country_code=au"
        f"&url={requests.utils.quote(search_url, safe='')}"
    )

    log.info(f"[AliExpress] {keyword}")
    try:
        resp = requests.get(proxy, timeout=90)
        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code}")
            return []

        soup     = BeautifulSoup(resp.text, "html.parser")
        products = []

        for script in soup.find_all("script"):
            text = script.string or ""
            if "listData" in text or "window._dida_config_" in text:
                titles = re.findall(r'"title"\s*:\s*"([^"]{10,100})"', text)
                prices = re.findall(r'"minPrice"\s*:\s*([\d.]+)', text)
                if not prices:
                    prices = re.findall(r'"formattedPrice"\s*:\s*"[A-Z$]*\s*([\d.]+)"', text)
                for i, title in enumerate(titles[:10]):
                    try:
                        price = float(prices[i]) if i < len(prices) else None
                        if price and (MIN_PRICE <= price <= MAX_PRICE):
                            products.append({
                                "name":      title[:120],
                                "source":    "AliExpress",
                                "category":  category,
                                "buy_price": price,
                                **calc_ebay(price),
                            })
                    except Exception:
                        continue
                if products:
                    break

        if not products:
            for card in soup.select("a[href*='/item/']")[:10]:
                try:
                    name_el  = card.select_one("[class*='title']") or card.select_one("h3")
                    price_el = card.select_one("[class*='price']")
                    if not name_el or not price_el:
                        continue
                    name = name_el.get_text(strip=True)
                    m    = re.search(r"[\d.]+", price_el.get_text(strip=True).replace(",", ""))
                    price = float(m.group()) if m else None
                    if price and (MIN_PRICE <= price <= MAX_PRICE):
                        products.append({
                            "name":      name[:120],
                            "source":    "AliExpress",
                            "category":  category,
                            "buy_price": price,
                            **calc_ebay(price),
                        })
                except Exception:
                    continue

        log.info(f"  -> {len(products)} products")
        return products

    except Exception as e:
        log.warning(f"  request error: {e}")
        return []


def run():
    log.info("=== Arbitrage scraper v2 starting ===")
    all_products = []

    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            all_products.extend(scrape_amazon_structured(kw, category))
            time.sleep(2)
            all_products.extend(scrape_aliexpress(kw, category))
            time.sleep(2)

    seen    = set()
    unique  = []
    for p in all_products:
        key = p["name"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    qualified = [p for p in unique if p["roi_pct"] >= 50]
    qualified.sort(key=lambda x: x["profit"], reverse=True)

    output = {
        "date":         date.today().isoformat(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total":        len(qualified),
        "products":     qualified,
    }

    os.makedirs("data", exist_ok=True)
    for path in [f"data/products_{date.today().isoformat()}.json", "data/latest.json"]:
        with open(path, "w") as f:
            json.dump(output, f, indent=2)

    log.info(f"=== Done. {len(qualified)} opportunities saved ===")


if __name__ == "__main__":
    run()
