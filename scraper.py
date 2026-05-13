"""
Dropshipping Arbitrage Scraper v3
Captures exact product URLs during scraping
"""

import os
import json
import time
import logging
import requests
import re
from datetime import date, datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
MIN_PRICE = 50.0
MAX_PRICE = 100.0

CATEGORIES = {
    "kitchen":  ["kitchen gadgets", "cookware set", "silicone baking", "coffee maker"],
    "pet":      ["automatic pet feeder", "cat litter box", "dog bed orthopedic"],
    "home":     ["smart home device", "cordless vacuum", "led smart bulb"],
    "employee": ["ergonomic chair cushion", "laptop stand aluminium", "usb c hub"],
}

def calc_ebay(buy):
    sell   = round(buy * 1.5, 2)
    profit = round(sell - buy, 2)
    roi    = round((profit / buy) * 100, 1)
    return {"ebay_price": sell, "profit": profit, "roi_pct": roi}

def parse_price(text):
    m = re.search(r"[\d,]+\.?\d*", str(text).replace(",", ""))
    return float(m.group()) if m else None

def scrape_amazon(keyword, category):
    if not SCRAPERAPI_KEY:
        return []
    url = "https://api.scraperapi.com/structured/amazon/search"
    params = {"api_key": SCRAPERAPI_KEY, "query": keyword, "country": "au"}
    log.info(f"[Amazon AU] {keyword}")
    try:
        resp = requests.get(url, params=params, timeout=60)
        if resp.status_code != 200:
            return []
        data    = resp.json()
        results = data.get("results", []) or data.get("organic_results", [])
        products = []
        for item in results[:10]:
            try:
                name  = item.get("name") or item.get("title", "")
                price = parse_price(item.get("price") or item.get("price_string") or "")
                
                # Get exact product URL from the result
                asin = item.get("asin") or item.get("product_id") or ""
                if asin:
                    source_url = f"https://www.amazon.com.au/dp/{asin}"
                else:
                    link = item.get("url") or item.get("link") or ""
                    source_url = link if link.startswith("http") else f"https://www.amazon.com.au/s?k={requests.utils.quote(name[:80])}"

                if not name or price is None:
                    continue
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue

                products.append({
                    "name":       name[:120],
                    "source":     "Amazon AU",
                    "category":   category,
                    "buy_price":  price,
                    "source_url": source_url,
                    **calc_ebay(price),
                })
            except Exception as e:
                log.debug(f"parse error: {e}")
        log.info(f"  -> {len(products)} products")
        return products
    except Exception as e:
        log.warning(f"request error: {e}")
        return []

def scrape_aliexpress(keyword, category):
    if not SCRAPERAPI_KEY:
        return []
    search_url = (
        f"https://www.aliexpress.com/wholesale"
        f"?SearchText={requests.utils.quote(keyword)}"
        f"&minPrice=50&maxPrice=100&currencyCode=AUD"
    )
    proxy = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPERAPI_KEY}"
        f"&render=true&country_code=au"
        f"&url={requests.utils.quote(search_url, safe='')}"
    )
    log.info(f"[AliExpress] {keyword}")
    try:
        resp = requests.get(proxy, timeout=90)
        if resp.status_code != 200:
            return []
        soup     = BeautifulSoup(resp.text, "html.parser")
        products = []

        # Try to extract product data including URLs from page JSON
        for script in soup.find_all("script"):
            text = script.string or ""
            if "listData" in text or "window._dida_config_" in text:
                titles   = re.findall(r'"title"\s*:\s*"([^"]{10,100})"', text)
                prices   = re.findall(r'"minPrice"\s*:\s*([\d.]+)', text)
                item_ids = re.findall(r'"productId"\s*:\s*"?(\d+)"?', text)
                if not prices:
                    prices = re.findall(r'"formattedPrice"\s*:\s*"[A-Z$]*\s*([\d.]+)"', text)
                for i, title in enumerate(titles[:10]):
                    try:
                        price = float(prices[i]) if i < len(prices) else None
                        if price and (MIN_PRICE <= price <= MAX_PRICE):
                            # Build exact product URL using item ID if available
                            if i < len(item_ids):
                                src_url = f"https://www.aliexpress.com/item/{item_ids[i]}.html"
                            else:
                                src_url = f"https://www.aliexpress.com/wholesale?SearchText={requests.utils.quote(title[:60])}"
                            products.append({
                                "name":       title[:120],
                                "source":     "AliExpress",
                                "category":   category,
                                "buy_price":  price,
                                "source_url": src_url,
                                **calc_ebay(price),
                            })
                    except Exception:
                        continue
                if products:
                    break

        # Fallback: parse cards and grab href links
        if not products:
            for card in soup.select("a[href*='/item/']")[:10]:
                try:
                    name_el  = card.select_one("[class*='title']") or card.select_one("h3")
                    price_el = card.select_one("[class*='price']")
                    if not name_el or not price_el:
                        continue
                    name  = name_el.get_text(strip=True)
                    price = parse_price(price_el.get_text(strip=True))
                    href  = card.get("href", "")
                    if href.startswith("//"):
                        href = "https:" + href
                    elif not href.startswith("http"):
                        href = "https://www.aliexpress.com" + href

                    if price and (MIN_PRICE <= price <= MAX_PRICE):
                        products.append({
                            "name":       name[:120],
                            "source":     "AliExpress",
                            "category":   category,
                            "buy_price":  price,
                            "source_url": href,
                            **calc_ebay(price),
                        })
                except Exception:
                    continue

        log.info(f"  -> {len(products)} products")
        return products
    except Exception as e:
        log.warning(f"request error: {e}")
        return []

def run():
    log.info("=== Arbitrage scraper v3 starting ===")
    all_products = []

    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            all_products.extend(scrape_amazon(kw, category))
            time.sleep(2)
            all_products.extend(scrape_aliexpress(kw, category))
            time.sleep(2)

    seen, unique = set(), []
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
