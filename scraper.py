"""
Dropshipping Arbitrage Scraper v4
Amazon AU + AliExpress scraping + eBay AU API for live listing data
"""

import os, json, time, logging, requests, re, base64
from datetime import date, datetime
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
EBAY_APP_ID    = os.environ.get("EBAY_APP_ID", "")
EBAY_CERT_ID   = os.environ.get("EBAY_CERT_ID", "")

MIN_PRICE = 50.0
MAX_PRICE = 100.0

CATEGORIES = {
    "kitchen":  ["kitchen gadgets", "cookware set", "silicone baking", "coffee maker"],
    "pet":      ["automatic pet feeder", "cat litter box", "dog bed orthopedic"],
    "home":     ["smart home device", "cordless vacuum", "led smart bulb"],
    "employee": ["ergonomic chair cushion", "laptop stand aluminium", "usb c hub"],
}

# ── eBay OAuth token ──────────────────────────────────────────────────────────

def get_ebay_token():
    """Get eBay OAuth application token."""
    if not EBAY_APP_ID or not EBAY_CERT_ID:
        log.warning("eBay credentials not set")
        return None
    try:
        credentials = base64.b64encode(
            f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode()
        ).decode()
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=30,
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            log.info("eBay token obtained successfully")
            return token
        log.warning(f"eBay token error: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        log.warning(f"eBay token exception: {e}")
        return None

# ── eBay Browse API ───────────────────────────────────────────────────────────

def search_ebay_au(name, token):
    """
    Search eBay AU for a product using Browse API.
    Returns dict with top listing URL, price, sold count, watchers.
    """
    if not token:
        return {}
    try:
        headers = {
            "Authorization":              f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID":    "EBAY_AU",
            "X-EBAY-C-ENDUSERCTX":        "contextualLocation=country%3DAU",
            "Content-Type":               "application/json",
        }
        params = {
            "q":           name[:80],
            "limit":       "5",
            "filter":      "buyingOptions:{FIXED_PRICE},conditions:{NEW}",
            "sort":        "bestMatch",
        }
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers=headers,
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            log.debug(f"eBay search {resp.status_code}: {resp.text[:100]}")
            return {}

        items = resp.json().get("itemSummaries", [])
        if not items:
            return {}

        top = items[0]
        price_val = float(
            top.get("price", {}).get("value", 0) or 0
        )
        ebay_item_url  = top.get("itemWebUrl", "")
        ebay_item_id   = top.get("itemId", "")
        seller         = top.get("seller", {}).get("username", "")
        condition      = top.get("condition", "")
        thumbnail      = top.get("image", {}).get("imageUrl", "")

        # Get additional details — watchers, sold count
        watchers  = top.get("watchCount", 0) or 0
        sold_count = 0
        for item in items:
            sc = item.get("soldQuantity") or item.get("unitSoldQuantity") or 0
            sold_count += int(sc)

        # Count total AU listings found
        total_listings = int(resp.json().get("total", 0))

        return {
            "ebay_url":        ebay_item_url,
            "ebay_price_aud":  round(price_val, 2),
            "ebay_listings":   total_listings,
            "ebay_sold":       sold_count,
            "ebay_watchers":   watchers,
            "ebay_seller":     seller,
            "ebay_condition":  condition,
        }
    except Exception as e:
        log.debug(f"eBay search error: {e}")
        return {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def calc_profit(buy):
    sell   = round(buy * 1.5, 2)
    profit = round(sell - buy, 2)
    roi    = round((profit / buy) * 100, 1)
    return {"ebay_price": sell, "profit": profit, "roi_pct": roi}

def parse_price(text):
    m = re.search(r"[\d,]+\.?\d*", str(text).replace(",", ""))
    return float(m.group()) if m else None

def clean_amazon_url(url):
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if not m:
        from urllib.parse import unquote
        m = re.search(r"/dp/([A-Z0-9]{10})", unquote(url))
    return f"https://www.amazon.com.au/dp/{m.group(1)}" if m else url

# ── Amazon AU scraper ─────────────────────────────────────────────────────────

def scrape_amazon(keyword, category):
    if not SCRAPERAPI_KEY:
        return []
    url    = "https://api.scraperapi.com/structured/amazon/search"
    params = {"api_key": SCRAPERAPI_KEY, "query": keyword, "country": "au"}
    log.info(f"[Amazon AU] {keyword}")
    try:
        resp = requests.get(url, params=params, timeout=60)
        if resp.status_code != 200:
            return []
        results  = resp.json().get("results", []) or resp.json().get("organic_results", [])
        products = []
        for item in results[:10]:
            name  = item.get("name") or item.get("title", "")
            price = parse_price(item.get("price") or item.get("price_string") or "")
            raw_url = item.get("url") or item.get("link") or ""
            asin    = item.get("asin") or item.get("product_id") or ""
            if asin:
                src_url = f"https://www.amazon.com.au/dp/{asin}"
            elif "/dp/" in raw_url:
                src_url = clean_amazon_url(raw_url)
            else:
                src_url = f"https://www.amazon.com.au/s?k={quote_plus(name[:80])}"
            if not name or price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue
            products.append({
                "name": name[:120], "source": "Amazon AU",
                "category": category, "buy_price": price,
                "source_url": src_url, **calc_profit(price),
            })
        log.info(f"  -> {len(products)} products")
        return products
    except Exception as e:
        log.warning(f"Amazon error: {e}")
        return []

# ── AliExpress scraper ────────────────────────────────────────────────────────

def scrape_aliexpress(keyword, category):
    if not SCRAPERAPI_KEY:
        return []
    search_url = (
        f"https://www.aliexpress.com/wholesale"
        f"?SearchText={quote_plus(keyword)}"
        f"&minPrice=50&maxPrice=100&currencyCode=AUD"
    )
    proxy = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPERAPI_KEY}"
        f"&render=true&country_code=au"
        f"&url={quote_plus(search_url)}"
    )
    log.info(f"[AliExpress] {keyword}")
    try:
        resp = requests.get(proxy, timeout=90)
        if resp.status_code != 200:
            return []
        soup     = BeautifulSoup(resp.text, "html.parser")
        products = []
        for script in soup.find_all("script"):
            text = script.string or ""
            if "listData" in text or "window._dida_config_" in text:
                titles   = re.findall(r'"title"\s*:\s*"([^"]{10,100})"', text)
                prices   = re.findall(r'"minPrice"\s*:\s*([\d.]+)', text)
                item_ids = re.findall(r'"productId"\s*:\s*"?(\d+)"?', text)
                for i, title in enumerate(titles[:10]):
                    try:
                        price = float(prices[i]) if i < len(prices) else None
                        if price and (MIN_PRICE <= price <= MAX_PRICE):
                            src_url = (
                                f"https://www.aliexpress.com/item/{item_ids[i]}.html"
                                if i < len(item_ids)
                                else f"https://www.aliexpress.com/wholesale?SearchText={quote_plus(title[:60])}"
                            )
                            products.append({
                                "name": title[:120], "source": "AliExpress",
                                "category": category, "buy_price": price,
                                "source_url": src_url, **calc_profit(price),
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
                    name  = name_el.get_text(strip=True)
                    price = parse_price(price_el.get_text(strip=True))
                    href  = card.get("href", "")
                    if href.startswith("//"):
                        href = "https:" + href
                    elif not href.startswith("http"):
                        href = "https://www.aliexpress.com" + href
                    if price and (MIN_PRICE <= price <= MAX_PRICE):
                        products.append({
                            "name": name[:120], "source": "AliExpress",
                            "category": category, "buy_price": price,
                            "source_url": href, **calc_profit(price),
                        })
                except Exception:
                    continue
        log.info(f"  -> {len(products)} products")
        return products
    except Exception as e:
        log.warning(f"AliExpress error: {e}")
        return []

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    log.info("=== Arbitrage scraper v4 starting ===")

    # Get eBay token once
    ebay_token = get_ebay_token()

    all_products = []
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            all_products.extend(scrape_amazon(kw, category))
            time.sleep(2)
            all_products.extend(scrape_aliexpress(kw, category))
            time.sleep(2)

    # Deduplicate
    seen, unique = set(), []
    for p in all_products:
        key = p["name"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    qualified = [p for p in unique if p["roi_pct"] >= 50]
    qualified.sort(key=lambda x: x["profit"], reverse=True)

    # Enrich with eBay AU live data
    log.info(f"Enriching {len(qualified)} products with eBay AU data...")
    for i, p in enumerate(qualified):
        log.info(f"  eBay lookup [{i+1}/{len(qualified)}]: {p['name'][:50]}")
        ebay_data = search_ebay_au(p["name"], ebay_token)
        p.update(ebay_data)
        time.sleep(0.5)  # respect rate limits

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

    log.info(f"=== Done. {len(qualified)} products with eBay data saved ===")

if __name__ == "__main__":
    run()
