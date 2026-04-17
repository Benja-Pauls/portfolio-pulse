<p align="center">
  <h1 align="center">Portfolio Pulse</h1>
  <p align="center">
    <strong>60+ CLI commands for portfolio intelligence + AI-generated magazine reports delivered to your phone.</strong>
  </p>
  <p align="center">
    Wall Street-grade analysis tools for self-directed investors.<br>
    SEC EDGAR insider filings. Billionaire 13F tracking. Recession probability dashboards.<br>
    ML price prediction. Congressional trade monitoring. Tax-aware trade modeling.<br>
    All from your terminal. All your data stays on your machine.
  </p>
  <p align="center">
    <a href="#-quick-start">Quick Start</a> &middot;
    <a href="#-cli-commands-60">All Commands</a> &middot;
    <a href="#-magazine-generator">Magazine</a> &middot;
    <a href="#-architecture">Architecture</a>
  </p>
</p>

---

## :sparkles: What is this?

Portfolio Pulse is two things:

1. **A CLI toolkit** with 60+ commands that pull real data from the Schwab API, SEC EDGAR, FRED, Finnhub, and more — giving you institutional-grade portfolio analysis from your terminal.

2. **A magazine generator** that uses those CLI tools + Claude Opus to produce beautiful, editorial-style HTML reports — then deploys them to Vercel with PIN authentication and sends you a push notification.

No financial advisor. No SaaS subscription. No data leaves your machine unless you choose to deploy the magazine.

---

## :camera: What the magazine looks like

The magazine is a self-contained HTML page with dark editorial typography (Fraunces + Inter), featuring:

- **Portfolio Snapshot** — total value, day change, all-time P&L
- **Market Pulse** — S&P 500, Nasdaq, VIX, Oil, Gold, Fear & Greed gauge
- **Macro Health** — yield curve, Treasury rates, recession signals
- **Holdings Table** — every position with price, day change, P&L, and RSI signals
- **AI Analysis** — Claude Opus-generated reasoning about what matters and what to do
- **Bottoming Opportunities** — stocks showing early recovery signals worth investigating

---

## :rocket: Quick Start

### Prerequisites

- Python 3.10+
- A [Schwab Developer](https://developer.schwab.com/) account (for live portfolio data)
- API keys for [Finnhub](https://finnhub.io/), [FRED](https://fred.stlouisfed.org/docs/api/), and optionally [Anthropic](https://console.anthropic.com/) (for Claude Opus analysis)

### 1. Clone

```bash
git clone https://github.com/Benja-Pauls/portfolio-pulse.git
cd portfolio-pulse
```

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the CLI toolkit directory with your API keys:

```env
# Schwab API (required for portfolio commands)
SCHWAB_APP_KEY=your_app_key
SCHWAB_APP_SECRET=your_app_secret
SCHWAB_CALLBACK_URL=https://127.0.0.1
SCHWAB_TOKEN_PATH=./token.json

# Finnhub (news, analyst ratings, insider trades, earnings)
FINNHUB_API_KEY=your_key

# FRED (macro data — rates, CPI, unemployment, yields)
FRED_API_KEY=your_key

# Anthropic (optional — for Claude Opus AI analysis in magazines)
ANTHROPIC_API_KEY=your_key

# Notifications (optional)
NOTIFY_TO_NUMBER=+1XXXXXXXXXX
```

### 4. Authenticate with Schwab

```bash
python schwab_cli.py auth
```

This launches a browser for OAuth login and saves the token locally.

### 5. Run your first command

```bash
python schwab_cli.py briefing --quick    # signal snapshot
python schwab_cli.py positions           # all holdings with P&L
python schwab_cli.py recession-check     # 10-indicator recession dashboard
```

### 6. Generate your first magazine

```bash
python generate_issue.py
open issues/$(date +%Y-%m-%d).html
```

---

## :wrench: CLI Commands (60+)

All commands are run via `python schwab_cli.py <command>`.

### :bank: Portfolio (Schwab API — Live)

| Command | Description |
|---------|-------------|
| `auth` | Test/refresh Schwab OAuth authentication |
| `summary` | Portfolio overview with allocation breakdown |
| `positions` | All holdings with gain/loss and current prices |
| `balances` | Cash, money market, buying power |
| `quote AAPL MSFT` | Real-time quotes for any symbols |
| `movers AAPL MSFT GOOG` | Side-by-side quote comparison |
| `history AAPL --period month` | Price history for a symbol |
| `transactions --days 30` | Recent account transactions |
| `export` | Dump positions as JSON |

### :moneybag: Trading (Live — Executes Real Trades)

| Command | Description |
|---------|-------------|
| `trade buy MSFT 67 --limit 374` | Place a limit buy order |
| `trade sell OEF 163 --limit 320` | Place a limit sell order |
| `trade orders` | Show recent orders and status |
| `trade status ORDER_ID` | Check a specific order |

### :newspaper: Briefing & Research

| Command | Description |
|---------|-------------|
| `briefing` | Full signal scan — **start here** |
| `briefing --quick` | Signals only, no web research prompts |
| `research <query>` | General web search for context |
| `verify-insider AAPL "Tim Cook"` | Check if an insider trade is a 10b5-1 plan |
| `sector-pulse all` | Sector rotation signals (inflow/outflow vs SPY) |
| `sector-pulse tech` | Single sector focus |
| `fed-watch` | Fed funds rate, yield curve, next FOMC date |
| `recession-check` | **10 weighted indicators** with recession probability % |

### :mag: Intelligence

| Command | Description |
|---------|-------------|
| `news IVV --days 7 --limit 10` | News with sentiment filtering |
| `sentiment AAPL --bullish-only` | Social sentiment analysis |
| `analyst AAPL --targets --earnings` | Analyst ratings, price targets, earnings estimates |
| `insider AAPL --open-market --buys-only --large 100000` | **SEC EDGAR Form 4** — insider buy/sell/price/value |
| `congress --politician pelosi --detail --ticker NVDA` | Congressional stock trades from House disclosures |
| `fear-greed` | CNN Fear & Greed Index + VIX |
| `macro` | Fed funds rate, CPI, unemployment, yields |
| `macro --indicator yields` | Focus on specific macro indicator |
| `etf-holdings IVV --limit 10` | Top holdings of any ETF |
| `overlap IVV OEF --show-common` | Holdings overlap between ETFs |

### :shield: Pre-Buy Due Diligence

| Command | Description |
|---------|-------------|
| `pre-buy MSFT` | **Mandatory before any buy** — runs price context, insider check, analyst consensus, fundamentals, technicals, tax impact. Outputs RED/YELLOW/GREEN verdict. |

### :chart_with_upwards_trend: Technical Analysis

| Command | Description |
|---------|-------------|
| `technicals IVV` | Full analysis: RSI, SMA 20/50/200, MACD, Bollinger, support/resistance |
| `technicals AAPL --signals-only` | Aggregate buy/sell/hold signal |

### :warning: Risk & Exposure

| Command | Description |
|---------|-------------|
| `risk --benchmark SPY --period 1y` | Sharpe, beta, max drawdown, Sortino per holding |
| `exposure --by sector` | True concentration across ETFs |
| `exposure --by stock` | Individual stock exposure including ETF holdings |
| `correlation --tickers IVV,GLD,EFV` | Correlation matrix with warnings |

### :crystal_ball: Forecasting

| Command | Description |
|---------|-------------|
| `monte-carlo IVV --days 90 --shares 87` | Price projections with probabilities |
| `arima IVV --days 30` | ARIMA forecast with 90% confidence intervals |
| `predict IVV --horizon 5` | ML direction prediction (GradientBoosting, 15 features) |
| `portfolio-forecast --days 252` | Correlated Monte Carlo for entire portfolio |
| `momentum` | Dual momentum rankings across 20+ tickers |

### :dart: Opportunity Detection

| Command | Description |
|---------|-------------|
| `opportunities --top 20` | Score 60+ tickers on pullback, portfolio gap, insider, fundamentals |
| `scan-pullbacks --max-range 30` | Find deep pullbacks that are recovering |
| `detect-bottoms --max-range 30` | **Early detection** — catches bottoming signals before the bounce |
| `price-context MSFT ISRG` | Where each sits in its 52-week range |

### :whale: Whale Tracking (13F Filings)

| Command | Description |
|---------|-------------|
| `whales --fund berkshire` | 13F holdings from SEC EDGAR |
| `whales AAPL` | Which major funds hold a stock |
| `whales --list-funds` | All 15 tracked funds: Buffett, Dalio, Soros, Druckenmiller, Ackman, etc. |

### :scales: Trade Planning

| Command | Description |
|---------|-------------|
| `compare IVV VOO VTI SCHD` | Returns, risk, yield, expense ratio, P/E |
| `what-if --sell OEF:all --buy VTI:52000` | Model a trade with tax impact |
| `screener --universe etf --min-yield 2 --max-expense 0.1` | Screen stocks/ETFs by criteria |
| `tax-harvest --min-loss 500` | Harvestable losses + swap suggestions |

### :test_tube: Backtesting & Position Sizing

| Command | Description |
|---------|-------------|
| `backtest-fear --symbol SPY` | What happens when you buy during extreme fear? |
| `backtest-sma --fast 50 --slow 200` | SMA crossover strategy vs buy-and-hold |
| `size-position MSFT --portfolio-value 307000` | Kelly criterion, volatility, risk-parity sizing |
| `earnings-guidance` | Are bellwether companies beating or missing estimates? |

### :receipt: Tax

| Command | Description |
|---------|-------------|
| `tax-profile` | Your tax rates (configurable per state) |
| `tax-impact` | Tax cost of selling each position now vs waiting for long-term rates |
| `tax-calc --gain 10000 --holding-period short` | Quick tax calculator |

### :chart_with_downwards_trend: Income & Earnings

| Command | Description |
|---------|-------------|
| `dividends IVV --shares 87` | Yield, history, projected income |
| `earnings-calendar` | Next earnings dates for all holdings |
| `income` | Projected annual income across all positions |

### :bar_chart: Dashboard & Visuals

| Command | Description |
|---------|-------------|
| `dashboard` | Portfolio + market pulse + signals |
| `ticker` | Flowing ticker tape with sparklines |
| `chart IVV --period 6mo` | ASCII price chart |
| `heatmap` | Performance heatmap by holding |
| `leaderboard --by sharpe` | Rankings by sharpe/return/momentum/yield/risk |

### :bell: Notifications

| Command | Description |
|---------|-------------|
| `sms-test` | Send a test notification to your phone |
| `sms-report` | Generate and send portfolio report via notification |
| `sms-report --dry-run` | Preview report without sending |

### :clipboard: Tracking

| Command | Description |
|---------|-------------|
| `watchlist show` | View watchlist |
| `watchlist add SCHD --note "High yield"` | Add to watchlist |
| `watchlist remove SCHD` | Remove from watchlist |
| `journal log --symbol X --side buy --shares 100 --price 50 --reason "..."` | Log a trade |
| `journal show` | Trade journal with current prices |
| `journal review` | Trades with verdict (was it a good trade?) |
| `alerts add --symbol IVV --below 600` | Set price alert |
| `alerts check` | Check which alerts have triggered |
| `drift set --targets '{"IVV":30}'` | Set target allocation |
| `drift show` | Show drift from targets |

---

## :newspaper: Magazine Generator

The magazine generator (`generate_issue.py`) pulls live market data and portfolio positions, runs bottoming signal detection across 20 tickers, calls Claude Opus for substantive AI analysis, and renders everything into a self-contained HTML page with editorial styling.

### How it works

```
generate_issue.py
    |
    +-- Fetches live prices via yfinance
    +-- Computes RSI, day change, P&L for all holdings
    +-- Scans 20 tickers for bottoming signals
    +-- Pulls Fear & Greed Index, yield curve, macro data
    +-- Calls Claude Opus API for AI analysis cards
    +-- Renders everything into a single HTML file
    +-- Outputs to issues/ (local) and public/ (Vercel)
```

### Vercel Deployment with PIN Authentication

The magazine is deployed to Vercel as a static site with server-side PIN authentication:

1. **Static HTML** is generated into `public/index.html`
2. **Vercel deploys** the `public/` directory automatically on push
3. **PIN gate** — a serverless function at `/api/login` validates the PIN and sets an HttpOnly cookie
4. **Content is hidden** until the PIN is entered — no JavaScript-only security, the cookie is HttpOnly and Secure

Configure the PIN in Vercel environment variables:

```bash
vercel env add PORTFOLIO_PIN
```

### Automated Delivery

A cron runner (`cron_runner.py`) schedules magazine generation 3x per day on weekdays (8:30 AM, 12:00 PM, 5:00 PM). It launches Claude Code as a non-interactive agent that:

1. Runs the full CLI briefing and bottoming signal detection
2. Web-searches for context on any unusual moves
3. Generates the magazine with AI analysis
4. Sends a notification with a link to the Vercel-hosted report

Safety guarantees:
- The agent prompt **explicitly forbids placing trades** — read-only analysis only
- Staleness detection prevents spam if the Mac was asleep
- Duplicate slot detection prevents running the same time slot twice

Install the cron schedule:

```bash
chmod +x setup_cron.sh
./setup_cron.sh
```

Remove it:

```bash
./teardown_cron.sh
```

---

## :building_construction: Architecture

```
portfolio-pulse/                    # This repo — magazine generation + Vercel deployment
  generate_issue.py                 # Data gathering + Claude Opus analysis + HTML rendering
  api/login.js                      # Vercel serverless function for PIN authentication
  public/                           # Vercel deploy target (gitignored, generated)
  issues/                           # Local archive of generated magazines (gitignored)
  vercel.json                       # Vercel configuration
  templates/                        # HTML templates (optional overrides)

Stock_Portfolio/                    # Sibling directory — CLI toolkit
  schwab_cli.py                     # Main CLI entry point + Schwab commands + trade execution
  intel.py                          # News, sentiment, analyst, insider (EDGAR Form 4), congress, macro
  analysis.py                       # Technicals, risk, exposure, correlation, compare
  planning.py                       # What-if, screener, watchlist, journal, alerts, drift, dividends
  dashboard.py                      # Ticker tape, dashboard, chart, heatmap, leaderboard
  forecast.py                       # Monte Carlo, ARIMA, ML predict, portfolio forecast, momentum
  whales.py                         # 13F institutional tracking via SEC EDGAR (15 billionaire funds)
  recession.py                      # 10-indicator weighted recession probability dashboard
  research.py                       # Briefing, sector-pulse, fed-watch, verify-insider
  backtest.py                       # Backtest-fear, backtest-sma, size-position, earnings-guidance
  tax.py                            # Tax-profile, tax-impact, tax-calc
  context.py                        # Price-context (52-week range analysis)
  opportunity.py                    # Opportunities scanner, scan-pullbacks
  earlydetect.py                    # Detect-bottoms (early bottoming signal detection)
  prebuy.py                         # Pre-buy (mandatory due diligence before any purchase)
  notify.py                         # Notifications via iMessage (macOS) or Pushover
  cron_runner.py                    # Scheduled Claude Code agent for automated analysis
  PRINCIPLES.md                     # Investment principles from Buffett, Munger, Dalio, et al.
  data/                             # Persistent storage (watchlist, journal, alerts, targets)
```

### Data Sources

| Source | What it provides | Auth |
|--------|-----------------|------|
| **Schwab API** | Live positions, balances, quotes, trade execution | OAuth 2.0 |
| **SEC EDGAR** | 13F filings (whale tracking), Form 4 (insider trades) | No key needed |
| **Finnhub** | News, analyst ratings, earnings, insider transactions | Free API key |
| **FRED** | Fed funds rate, CPI, unemployment, yields, housing | Free API key |
| **yfinance** | Historical prices, ETF holdings, dividends | No key needed |
| **CNN Fear & Greed** | Market sentiment index | No key needed |
| **House Disclosures** | Congressional stock trades | No key needed |

### Rate Limits

- **Finnhub**: 60 requests/minute
- **FRED**: Unlimited
- **SEC EDGAR**: 10 requests/second (no key needed)
- **yfinance**: Unofficial, no key (be respectful)

---

## :gear: Configuration

### Portfolio Setup

Edit the `positions` list in `generate_issue.py` to match your holdings:

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

### Tax Configuration

The CLI supports state-specific tax rates. Edit `tax.py` to match your state:

```python
# Default: Wisconsin single filer
FEDERAL_RATE = 0.24
STATE_RATE = 0.063
SHORT_TERM_RATE = 0.303   # federal + state
LONG_TERM_RATE = 0.194    # 15% federal + state
```

---

## :handshake: Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Areas where help is especially appreciated:
- Additional data source integrations (e.g., Options flow, dark pool data)
- Support for brokerages beyond Schwab (TD Ameritrade, Fidelity, IBKR)
- Cross-platform notification support (Linux, Windows)
- Additional ML models for price prediction
- Magazine template themes
- Test coverage

---

## :books: Tech Stack

- **Python** — CLI toolkit and magazine generator
- **[Click](https://click.palletsprojects.com/)** + **[Rich](https://rich.readthedocs.io/)** — beautiful terminal output
- **[schwab-py](https://github.com/alexgolec/schwab-py)** — Schwab API client
- **[yfinance](https://github.com/ranaroussi/yfinance)** — market data
- **[scikit-learn](https://scikit-learn.org/)** — ML price prediction
- **[statsmodels](https://www.statsmodels.org/)** — ARIMA forecasting
- **[Claude Opus](https://anthropic.com/)** — AI analysis in magazines
- **[Vercel](https://vercel.com/)** — magazine hosting with serverless PIN auth
- **[Claude Code](https://claude.ai/code)** — automated agent for scheduled analysis

---

## :page_facing_up: License

[MIT](LICENSE) — use it, fork it, make money with it.

---

<p align="center">
  Built for self-directed investors who want Wall Street tools without the Wall Street fees.<br>
  <sub>Not financial advice. Always do your own research.</sub>
</p>
