# Portfolio Pulse 📊

**AI-powered investment portfolio magazine** — daily editorial-style market analysis rendered as beautiful HTML and delivered to your phone via iMessage.

Your data never leaves your machine. No cloud hosting. No accounts. Just clone, configure, and go.

Built with [Claude Code](https://claude.ai/code).

---

## What it does

Three times a day (8:30 AM, 12 PM, 5 PM), Claude Code runs a full portfolio analysis and generates a self-contained HTML magazine with:

- **📊 Portfolio Snapshot** — total value, day change, all-time P&L
- **🌍 Market Pulse** — S&P 500, Nasdaq, VIX, Oil, Gold, Fear & Greed gauge
- **🏛️ Macro Health** — yield curve, Treasury rates, recession signals
- **💼 Holdings** — every position with price, day change, P&L, and RSI signals
- **⚠️ AI Analysis** — actual reasoning about what's happening and what to do:
  - "MSFT +4.7% on Iran ceasefire + AI rally — hold through Apr 29 earnings"
  - "EFV RSI 76 overbought — don't add, wait for 5-8% pullback"
  - "21% cash position costs ~$3K/yr in opportunity cost"
- **🔍 Opportunities** — stocks showing early bottoming signals worth investigating

The HTML is saved locally and the file path is sent to your phone via iMessage. Tap it, it opens in Safari. Your financial data never touches the internet.

## Screenshots

*[Screenshots of the dark-themed magazine with editorial typography]*

## Quick Start

### 1. Clone

```bash
git clone https://github.com/Benja-Pauls/portfolio-pulse.git
cd portfolio-pulse
```

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install yfinance fear-and-greed numpy python-dotenv
```

### 3. Configure your portfolio

Edit the `positions` list in `generate_issue.py`:

```python
positions = [
    {"symbol": "VOO", "shares": 100, "cost": 40000, "name": "Vanguard S&P 500"},
    {"symbol": "SCHD", "shares": 200, "cost": 6000, "name": "Schwab Dividend"},
    {"symbol": "MSFT", "shares": 50, "cost": 18000, "name": "Microsoft"},
    # Add your holdings here
]
cash = 25000   # cash/money market balance
cd = 0         # CDs or fixed income
```

### 4. Configure notifications

Create a `.env` file:

```
NOTIFY_TO_NUMBER=+1XXXXXXXXXX  # your phone number for iMessage
```

### 5. Generate your first issue

```bash
python generate_issue.py
open issues/$(date +%Y-%m-%d).html
```

### 6. Set up automated delivery (macOS)

Run the included setup script to install cron jobs:

```bash
chmod +x setup_cron.sh
./setup_cron.sh
```

This schedules Claude Code to run 3x/day (weekdays), generate the magazine with AI analysis, and iMessage you the file.

## How notifications work

On macOS, Portfolio Pulse uses AppleScript to send iMessages through the built-in Messages app. No Twilio, no SMS provider, no registration. Messages come from your own Apple ID.

**Requirements:**
- macOS with Messages app signed into iMessage
- Your Mac needs to be awake (enable "Wake for network access" in Battery settings)

## Architecture

```
portfolio-pulse/
├── generate_issue.py    # Data gathering + HTML magazine rendering
├── setup_cron.sh        # Install cron schedule (3x/day weekdays)
├── teardown_cron.sh     # Remove cron schedule
├── issues/              # Generated HTML files (local only, gitignored)
│   ├── 2026-04-15.html
│   └── ...
├── .env                 # Your phone number (gitignored)
└── README.md
```

## Optional: Full analysis CLI

For deeper analysis, pair Portfolio Pulse with the [Stock Portfolio CLI](https://github.com/Benja-Pauls/portfolio-pulse/wiki/CLI) toolkit which includes 60+ commands:
- Real-time Schwab API integration (positions, balances, trading)
- Technical analysis (RSI, SMA, MACD, Bollinger Bands)
- Recession probability dashboard (10 weighted indicators)
- Insider trading from SEC EDGAR Form 4 filings
- Congressional stock trades from House disclosures
- Whale tracking (Buffett, Soros, Druckenmiller 13F holdings)
- Monte Carlo, ARIMA, and ML price predictions
- Pre-buy due diligence with insider + fundamentals check
- Tax-aware trade modeling (state-specific rates)

## Powered by

- **[yfinance](https://github.com/ranaroussi/yfinance)** — market data
- **[fear-and-greed](https://pypi.org/project/fear-and-greed/)** — CNN Fear & Greed Index
- **[Claude Code](https://claude.ai/code)** — AI analysis and magazine generation
- **Google Fonts** — Fraunces + Inter editorial typography

## License

MIT — use it, fork it, make money with it.
