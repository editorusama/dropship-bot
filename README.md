# Dropshipping Arbitrage Bot

Scrapes **Amazon AU** and **AliExpress** daily, filters products priced
$50–$100, and calculates eBay resale prices for 50% ROI.

Results are saved to `data/latest.json` and committed automatically each morning.

---

## Setup (one-time, ~10 minutes)

### 1. Get a free ScraperAPI key
1. Go to [scraperapi.com](https://www.scraperapi.com) and sign up free
2. Copy your API key from the dashboard (1,000 free calls/month)

### 2. Create your GitHub repository
```bash
git init dropship-bot
cd dropship-bot
# Copy all files from this folder into it
git add .
git commit -m "initial commit"
gh repo create dropship-bot --public --push
# or push manually to github.com
```

### 3. Add your API key as a GitHub Secret
1. Go to your repo on GitHub
2. Click **Settings → Secrets and variables → Actions**
3. Click **New repository secret**
4. Name: `SCRAPERAPI_KEY`
5. Value: paste your ScraperAPI key
6. Click **Add secret**

### 4. Enable GitHub Actions
1. Click the **Actions** tab in your repo
2. Click **I understand my workflows, go ahead and enable them**

That's it. The bot now runs every day at 8am AEST automatically.

---

## Running manually
Either click **Run workflow** in the Actions tab, or locally:

```bash
pip install -r requirements.txt
export SCRAPERAPI_KEY=your_key_here
python scraper.py
```

---

## Output format

`data/latest.json` contains:
```json
{
  "date": "2026-05-12",
  "generated_at": "2026-05-12T22:00:05Z",
  "total": 24,
  "products": [
    {
      "name": "Non-stick ceramic frying pan set",
      "source": "Amazon AU",
      "category": "kitchen",
      "buy_price": 62.99,
      "ebay_price": 94.49,
      "profit": 31.50,
      "roi_pct": 50.0
    }
  ]
}
```

---

## ROI formula

```
eBay price  = buy price × 1.50
Profit      = eBay price − buy price
ROI         = (profit / buy price) × 100   →  always 50%
```

---

## Customising

| What to change | Where |
|---|---|
| Price range ($50–$100) | `MIN_PRICE` / `MAX_PRICE` in `scraper.py` |
| ROI target (50%) | `ROI_TARGET` in `scraper.py` |
| Categories & keywords | `CATEGORIES` dict in `scraper.py` |
| Run time (8am AEST) | `cron` line in `.github/workflows/daily_scraper.yml` |

---

## Cron time reference

| Your timezone | Cron value |
|---|---|
| 8am AEST (Sydney) | `0 22 * * *` |
| 6am AEST | `0 20 * * *` |
| Midnight AEST | `0 14 * * *` |

Use [crontab.guru](https://crontab.guru) to convert times.
