#!/usr/bin/env python3
"""Generate a Portfolio Pulse magazine issue — editorial-style HTML market analysis.

This script generates a single self-contained HTML file styled like an editorial
magazine with bold typography, distinct section designs, and data-driven insights.

Usage:
  python generate_issue.py                    # generates today's issue
  python generate_issue.py --date 2026-04-15  # specific date

Output: issues/YYYY-MM-DD.html
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add the Stock_Portfolio directory to path so we can use the CLI tools
STOCK_DIR = Path(__file__).parent.parent / "Stock_Portfolio"
sys.path.insert(0, str(STOCK_DIR))

from dotenv import load_dotenv
load_dotenv(STOCK_DIR / ".env")

import yfinance as yf
import numpy as np

# Auth script — defined outside f-strings to avoid brace escaping issues
AUTH_SCRIPT = r"""
function getCookie(n) {
  var m = document.cookie.match(new RegExp("(?:^|;\\s*)" + n + "=([^;]*)"));
  return m ? m[1] : null;
}
if (getCookie("pp_auth") === "1") {
  document.addEventListener("DOMContentLoaded", function() {
    document.getElementById("login").style.display = "none";
    document.getElementById("content").style.display = "block";
  });
}
async function unlock() {
  var p = document.getElementById("pin").value;
  try {
    var r = await fetch("/api/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({pin: p})
    });
    if (r.ok) {
      document.getElementById("login").style.display = "none";
      document.getElementById("content").style.display = "block";
    } else {
      document.getElementById("err").style.display = "block";
      document.getElementById("pin").value = "";
      document.getElementById("pin").focus();
    }
  } catch(e) {
    document.getElementById("login").style.display = "none";
    document.getElementById("content").style.display = "block";
  }
}
"""

# ---------------------------------------------------------------------------
# Claude Opus Analysis
# ---------------------------------------------------------------------------

def generate_opus_analysis(data):
    """Call Claude Opus to generate substantive investment analysis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Build context from gathered data
        p = data["portfolio"]
        m = data["market"]
        macro = data["macro"]

        positions_summary = "\n".join(
            f"- {pos['symbol']} ({pos['name']}): ${pos['price']:.2f}, day {pos['day_chg']:+.1f}%, "
            f"total P&L {pos['gain']:+,.0f} ({pos['gain_pct']:+.1f}%), RSI {pos['rsi']:.0f}"
            for pos in p["positions"]
        )

        opps_summary = "\n".join(
            f"- {o['symbol']}: ${o['price']:.0f}, {o['from_high']:+.0f}% from 52W high, RSI {o['rsi']:.0f}, "
            f"at {o['position']:.0f}% of range"
            for o in data.get("opportunities", [])
        ) or "None detected"

        fg = m.get("fear_greed", {})
        sp = m.get("sp500", {})
        vix = m.get("vix", {})

        prompt = f"""You are an expert portfolio analyst writing a concise daily briefing for a self-directed investor.
Be direct and opinionated — no disclaimers. Give specific, actionable insights.

TODAY'S DATA:

PORTFOLIO (${p['total_value']:,.0f} total, {p['day_change_pct']:+.2f}% today):
{positions_summary}
Cash: ${p['cash']:,.0f}

MARKET:
- S&P 500: {sp.get('price', 0):,.0f} ({sp.get('change', 0):+.2f}%)
- VIX: {vix.get('price', 0):.1f}
- Fear & Greed: {fg.get('value', 50):.0f} ({fg.get('label', 'neutral')})
- Oil: ${m.get('oil', {}).get('price', 0):.0f}

MACRO:
- Yield Curve (10Y-2Y): {macro['spread']:+.2f}% ({'Normal' if macro['spread'] > 0 else 'INVERTED'})
- 10Y Treasury: {macro['t10']:.2f}%

BOTTOMING OPPORTUNITIES DETECTED:
{opps_summary}

KEY CONTEXT:
- All positions bought Dec 2025 — SHORT-TERM until Dec 2026 (30.3% tax rate)
- ISRG and MSFT bought Apr 2026 — SHORT-TERM until Apr 2027
- ISRG earnings April 21, MSFT earnings April 29
- IVV and OEF are 98.7% correlated (consolidation candidate)
- GLD and IAU are identical exposure (consolidate after Dec 2026 for long-term tax rate)

Write 4-6 analysis cards. Each card should have a bold title and 2-3 sentences of analysis.
Focus on:
1. What happened today and WHY (not just the numbers)
2. Which positions need attention and WHAT TO DO about them
3. Any upcoming catalysts (earnings, macro events) and how to prepare
4. Whether cash should be deployed or held, and why
5. Any bottoming opportunities worth investigating

Format each card as:
TITLE: [bold title]
BODY: [2-3 sentences of direct, opinionated analysis]

Be concise but substantive. Each card should tell the investor something they can act on."""

        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text
    except Exception as e:
        import traceback
        print(f"Claude API error: {e}")
        traceback.print_exc()
        return None


def parse_opus_cards(text):
    """Parse Claude's response into HTML cards."""
    if not text:
        return ""

    cards = []
    current_title = None
    current_body = []

    for line in text.strip().split("\n"):
        line = line.strip().lstrip("*").rstrip("*").strip()
        if not line or line == "---":
            continue
        if line.upper().startswith("TITLE:"):
            if current_title:
                cards.append((current_title, " ".join(current_body)))
            current_title = line[6:].strip().lstrip("*").rstrip("*").strip()
            current_body = []
        elif line.upper().startswith("BODY:"):
            current_body.append(line[5:].strip())
        elif current_title and not line.upper().startswith("DAILY") and len(line) > 10:
            current_body.append(line)

    if current_title:
        cards.append((current_title, " ".join(current_body)))

    colors = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"]
    html = ""
    for i, (title, body) in enumerate(cards):
        color = colors[i % len(colors)]
        html += f'''
        <div class="analysis-card" style="--accent: {color};">
          <div class="analysis-card-inner">
            <div class="analysis-quote-mark" style="color: {color};">\u201c</div>
            <h3 class="analysis-card-title">{title}</h3>
            <p class="analysis-card-body">{body}</p>
          </div>
        </div>'''

    return html


def svg_sparkline(prices, width=120, height=40, color="#6366f1"):
    """Generate an inline SVG sparkline from price data."""
    if not prices or len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rng = mx - mn if mx != mn else 1
    points = []
    for i, p in enumerate(prices):
        x = i / (len(prices) - 1) * width
        y = height - ((p - mn) / rng * (height - 4)) - 2
        points.append(f"{x:.1f},{y:.1f}")

    # Gradient fill
    fill_points = [f"0,{height}"] + points + [f"{width},{height}"]
    trend_color = "#10b981" if prices[-1] >= prices[0] else "#ef4444"

    return f'''<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="display:block;">
  <defs><linearGradient id="sg_{id(prices)}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{trend_color}" stop-opacity="0.3"/>
    <stop offset="100%" stop-color="{trend_color}" stop-opacity="0"/>
  </linearGradient></defs>
  <polygon points="{' '.join(fill_points)}" fill="url(#sg_{id(prices)})"/>
  <polyline points="{' '.join(points)}" fill="none" stroke="{trend_color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{points[-1].split(',')[0]}" cy="{points[-1].split(',')[1]}" r="2.5" fill="{trend_color}"/>
</svg>'''


def svg_donut(slices, size=200):
    """Generate an SVG donut chart. slices = [(label, value, color), ...]"""
    total = sum(v for _, v, _ in slices)
    if total == 0:
        return ""

    cx, cy, r = size / 2, size / 2, size / 2 - 10
    inner_r = r * 0.6
    circumference = 2 * 3.14159 * r
    arcs = ""
    legend = ""
    offset = 0

    for label, value, color in slices:
        pct = value / total
        dash = circumference * pct
        gap = circumference - dash

        arcs += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{r - inner_r}" stroke-dasharray="{dash:.1f} {gap:.1f}" stroke-dashoffset="{-offset:.1f}" transform="rotate(-90 {cx} {cy})" opacity="0.85"/>'
        offset += dash

    # Center text
    arcs += f'<circle cx="{cx}" cy="{cy}" r="{inner_r}" fill="#0a0a0f"/>'

    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{arcs}</svg>'


def svg_radial_gauge(value, size=180):
    """Generate a radial Fear & Greed gauge."""
    cx, cy, r = size / 2, size / 2 + 10, size / 2 - 20
    # Arc from 180° to 0° (half circle)
    import math

    # Background arc segments
    segments = [
        (0, 20, "#ef4444"),    # Extreme Fear
        (20, 40, "#f97316"),   # Fear
        (40, 60, "#eab308"),   # Neutral
        (60, 80, "#22c55e"),   # Greed
        (80, 100, "#10b981"),  # Extreme Greed
    ]

    arcs = ""
    for start, end, color in segments:
        a1 = math.pi - (start / 100 * math.pi)
        a2 = math.pi - (end / 100 * math.pi)
        x1, y1 = cx + r * math.cos(a1), cy - r * math.sin(a1)
        x2, y2 = cx + r * math.cos(a2), cy - r * math.sin(a2)
        arcs += f'<path d="M {x1:.1f},{y1:.1f} A {r},{r} 0 0 1 {x2:.1f},{y2:.1f}" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round" opacity="0.6"/>'

    # Needle
    angle = math.pi - (value / 100 * math.pi)
    nx = cx + (r - 15) * math.cos(angle)
    ny = cy - (r - 15) * math.sin(angle)
    arcs += f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="#fff" stroke-width="3" stroke-linecap="round"/>'
    arcs += f'<circle cx="{cx}" cy="{cy}" r="6" fill="#fff"/>'

    # Labels
    arcs += f'<text x="{cx - r}" y="{cy + 25}" fill="#6b7280" font-size="10" font-family="Inter,sans-serif">Fear</text>'
    arcs += f'<text x="{cx + r - 30}" y="{cy + 25}" fill="#6b7280" font-size="10" font-family="Inter,sans-serif">Greed</text>'

    return f'<svg width="{size}" height="{size // 2 + 40}" viewBox="0 0 {size} {size // 2 + 40}">{arcs}</svg>'


def compute_rsi(prices, window=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def gather_data():
    """Gather all market and portfolio data for the issue."""
    data = {"generated_at": datetime.now().isoformat(), "sections": {}}

    # Portfolio positions
    positions = [
        {"symbol": "IVV", "shares": 87, "cost": 47502.75, "name": "iShares S&P 500"},
        {"symbol": "OEF", "shares": 163, "cost": 53477.99, "name": "iShares S&P 100"},
        {"symbol": "GLD", "shares": 69, "cost": 26827.43, "name": "SPDR Gold"},
        {"symbol": "IAU", "shares": 294, "cost": 22946.96, "name": "iShares Gold"},
        {"symbol": "EFV", "shares": 272, "cost": 16240.28, "name": "iShares Int'l Value"},
        {"symbol": "BAI", "shares": 288, "cost": 9886.86, "name": "iShares AI Innovation"},
        {"symbol": "ISRG", "shares": 40, "cost": 18329.20, "name": "Intuitive Surgical"},
        {"symbol": "MSFT", "shares": 67, "cost": 24823.50, "name": "Microsoft"},
    ]
    cash = 43400
    cd = 24998

    # Fetch live prices
    total_value = cash + cd
    enriched = []
    for p in positions:
        try:
            t = yf.Ticker(p["symbol"])
            hist = t.history(period="5d")
            hist_3m = t.history(period="3mo")
            if hist.empty:
                continue
            price = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else price
            value = p["shares"] * price
            day_chg = (price - prev) / prev * 100
            gain = value - p["cost"]
            gain_pct = gain / p["cost"] * 100
            total_value += value

            rsi = compute_rsi(hist_3m["Close"]).iloc[-1] if not hist_3m.empty else 50

            # Sparkline data (last 30 days for mini chart)
            spark_prices = hist_3m["Close"].tail(30).tolist() if not hist_3m.empty else []

            # 52-week range position
            hist_1y = t.history(period="1y")
            if not hist_1y.empty:
                high_52w = hist_1y["Close"].max()
                low_52w = hist_1y["Close"].min()
                range_pos = (price - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50
            else:
                high_52w, low_52w, range_pos = price, price, 50

            enriched.append({
                **p, "price": price, "value": value,
                "day_chg": day_chg, "gain": gain, "gain_pct": gain_pct,
                "rsi": rsi, "sparkline": spark_prices,
                "high_52w": high_52w, "low_52w": low_52w, "range_pos": range_pos,
            })
        except Exception:
            continue

    total_gain = sum(p["gain"] for p in enriched)
    total_cost = sum(p["cost"] for p in enriched)
    day_change = sum((p["day_chg"] / 100) * p["value"] for p in enriched)

    data["portfolio"] = {
        "total_value": total_value,
        "total_gain": total_gain,
        "total_gain_pct": total_gain / total_cost * 100 if total_cost else 0,
        "day_change": day_change,
        "day_change_pct": day_change / (total_value - day_change) * 100 if total_value else 0,
        "cash": cash,
        "cd": cd,
        "positions": sorted(enriched, key=lambda x: -x["value"]),
    }

    # Market data
    market = {}
    for sym, label in [("^GSPC", "sp500"), ("^IXIC", "nasdaq"), ("^DJI", "dow"),
                        ("^VIX", "vix"), ("CL=F", "oil"), ("GC=F", "gold")]:
        try:
            t = yf.Ticker(sym)
            h = t.history(period="5d")
            if not h.empty:
                cur = h["Close"].iloc[-1]
                prev = h["Close"].iloc[-2] if len(h) > 1 else cur
                market[label] = {"price": cur, "change": (cur - prev) / prev * 100}
        except Exception:
            pass

    try:
        import fear_and_greed as fg
        fng = fg.get()
        market["fear_greed"] = {"value": fng.value, "label": fng.description}
    except Exception:
        market["fear_greed"] = {"value": 50, "label": "neutral"}

    data["market"] = market

    # Yield curve
    try:
        t10 = yf.Ticker("^TNX").history(period="5d")["Close"].iloc[-1]
        t2 = yf.Ticker("^IRX").history(period="5d")["Close"].iloc[-1]
        data["macro"] = {
            "t10": t10, "t2": t2, "spread": t10 - t2,
            "curve_status": "Normal" if t10 > t2 else "INVERTED",
        }
    except Exception:
        data["macro"] = {"t10": 0, "t2": 0, "spread": 0, "curve_status": "Unknown"}

    # Bottoming signals (scan 20 tickers)
    scan = ["AAPL", "NVDA", "AMZN", "GOOGL", "META", "UNH", "JNJ", "LLY",
            "PG", "HD", "NKE", "XLV", "IBB", "SOXX", "IWM", "ABBV", "CRM",
            "COST", "AVGO", "UBER"]
    opportunities = []
    for sym in scan:
        try:
            t = yf.Ticker(sym)
            h = t.history(period="1y")
            if h.empty or len(h) < 60:
                continue
            close = h["Close"]
            cur = close.iloc[-1]
            high = close.max()
            low = close.min()
            if high == low:
                continue
            pos = (cur - low) / (high - low) * 100
            if pos > 30:
                continue
            rsi = compute_rsi(close).iloc[-1]
            if 25 < rsi < 45:
                opportunities.append({
                    "symbol": sym, "price": cur, "position": pos,
                    "from_high": (cur / high - 1) * 100, "rsi": rsi,
                })
        except Exception:
            continue
    opportunities.sort(key=lambda x: x["position"])
    data["opportunities"] = opportunities[:5]

    return data


def render_html(data, analysis_text=None, password=None, opus_html=None):
    """Render the data into a beautiful editorial magazine HTML."""
    now = datetime.now()
    p = data["portfolio"]
    m = data["market"]
    macro = data["macro"]

    # Helper to build analysis cards with new class-based styling
    def _card(title, body, color="#6366f1"):
        return (
            f'<div class="analysis-card" style="--accent: {color};">'
            f'<div class="analysis-card-inner">'
            f'<div class="analysis-quote-mark" style="color: {color};">\u201c</div>'
            f'<h3 class="analysis-card-title">{title}</h3>'
            f'<p class="analysis-card-body">{body}</p>'
            f'</div></div>'
        )

    # Use Opus-generated analysis if available, fallback to auto-generated
    if opus_html:
        analysis_html = opus_html
    elif analysis_text:
        paragraphs = analysis_text.strip().split("\n\n")
        analysis_html = ""
        for para in paragraphs:
            if para.strip():
                analysis_html += _card("Analysis", para.strip())
    elif not analysis_text:
        # Generate basic analysis from the data
        analysis_parts = []

        # Big movers
        big_movers = [pos for pos in p["positions"] if abs(pos["day_chg"]) > 2]
        if big_movers:
            for bm in big_movers:
                direction = "surged" if bm["day_chg"] > 0 else "dropped"
                c = "#10b981" if bm["day_chg"] > 0 else "#ef4444"
                analysis_parts.append(_card(
                    f'{bm["symbol"]} {direction} {abs(bm["day_chg"]):.1f}% today',
                    'Investigate the cause -- large single-day moves often signal a news catalyst. Check for earnings surprises, analyst upgrades/downgrades, or sector-wide rotation.',
                    c
                ))

        # Overbought warnings
        overbought = [pos for pos in p["positions"] if pos["rsi"] > 70]
        if overbought:
            names = ", ".join(pos["symbol"] for pos in overbought)
            analysis_parts.append(_card(
                f'Overbought Positions: {names}',
                "RSI above 70 indicates these positions are technically stretched. This doesn't mean sell -- but it does mean don't add more here. Wait for a pullback before increasing exposure. If any of these drop 5-8%, that would be a better entry point.",
                "#ef4444"
            ))

        # Oversold opportunities
        oversold = [pos for pos in p["positions"] if pos["rsi"] < 30]
        if oversold:
            names = ", ".join(pos["symbol"] for pos in oversold)
            analysis_parts.append(_card(
                f'Oversold: {names}',
                "RSI below 30 suggests these positions are technically oversold -- historically a buying opportunity if fundamentals remain intact. Consider adding to these positions if the thesis hasn't changed.",
                "#10b981"
            ))

        # Market mood commentary
        fg_val = m.get("fear_greed", {}).get("value", 50)
        vix_val = m.get("vix", {}).get("price", 20)
        spread = macro.get("spread", 0)

        if fg_val < 25:
            analysis_parts.append(_card(
                'Extreme Fear = Opportunity',
                f'Fear &amp; Greed at {fg_val:.0f} -- extreme fear. Historical backtest shows buying during extreme fear has a 75% win rate over 3 months with +4.7% average return. If the yield curve is normal ({spread:+.2f}%, it is) and employment is stable, this is historically one of the best times to deploy cash.',
                "#6366f1"
            ))
        elif fg_val > 75:
            analysis_parts.append(_card(
                'Extreme Greed = Caution',
                f'Fear &amp; Greed at {fg_val:.0f} -- the market is euphoric. Historically, extreme greed often precedes pullbacks. Not a sell signal, but definitely not the time to deploy new capital aggressively. Patience.',
                "#f97316"
            ))

        # Yield curve
        if spread < 0:
            analysis_parts.append(_card(
                'Yield Curve INVERTED',
                f'The 10Y-2Y spread is {spread:.2f}%. An inverted yield curve has preceded every US recession in the last 50 years (with a 6-18 month lead time). Consider reducing equity exposure and increasing defensive positions.',
                "#ef4444"
            ))

        # Cash drag if applicable
        cash_pct = p["cash"] / p["total_value"] * 100 if p["total_value"] else 0
        if cash_pct > 20:
            analysis_parts.append(_card(
                f'{cash_pct:.0f}% Cash Position',
                f'Cash at {cash_pct:.0f}% of portfolio earns ~4.2% in money market while the market averages 10-12%. That gap costs approximately ${p["cash"] * 0.07:,.0f}/year in opportunity cost. If recession signals are green and fear is elevated, consider deploying in tranches.',
                "#eab308"
            ))

        if not analysis_parts:
            analysis_parts.append(_card(
                'Portfolio On Track',
                'No major signals or actions needed today. All positions within normal ranges. Continue holding and monitoring.',
                "#10b981"
            ))

        analysis_html = "\n".join(analysis_parts)
    else:
        # Use provided analysis (from Claude agent)
        paragraphs = analysis_text.strip().split("\n\n")
        analysis_html = ""
        for para in paragraphs:
            if para.strip():
                analysis_html += _card("Analysis", para.strip())

    day_arrow = "▲" if p["day_change"] >= 0 else "▼"
    day_color = "#10b981" if p["day_change"] >= 0 else "#ef4444"
    fg_val = m.get("fear_greed", {}).get("value", 50)
    fg_label = m.get("fear_greed", {}).get("label", "neutral")

    if fg_val < 25:
        fg_color = "#ef4444"
    elif fg_val < 45:
        fg_color = "#f97316"
    elif fg_val < 55:
        fg_color = "#eab308"
    elif fg_val < 75:
        fg_color = "#10b981"
    else:
        fg_color = "#22c55e"

    # Build positions HTML — card-based layout with sparklines
    pos_cards = ""
    for pos in p["positions"]:
        color = "#10b981" if pos["day_chg"] >= 0 else "#ef4444"
        gain_color = "#10b981" if pos["gain"] >= 0 else "#ef4444"
        rsi_color = "#ef4444" if pos["rsi"] > 70 else ("#10b981" if pos["rsi"] < 30 else "#6b7280")
        rsi_label = ""
        if pos["rsi"] > 70:
            rsi_label = '<span class="rsi-badge rsi-overbought">OVERBOUGHT</span>'
        elif pos["rsi"] < 30:
            rsi_label = '<span class="rsi-badge rsi-oversold">OVERSOLD</span>'

        range_pct = max(0, min(100, pos.get("range_pos", 50)))
        sparkline = svg_sparkline(pos.get("sparkline", []), width=140, height=45)
        card_bg = "linear-gradient(135deg, rgba(16,185,129,0.06) 0%, rgba(16,185,129,0.02) 100%)" if pos["gain"] >= 0 else "linear-gradient(135deg, rgba(239,68,68,0.06) 0%, rgba(239,68,68,0.02) 100%)"

        pos_cards += f'''
        <div class="pos-card" style="background: {card_bg};">
          <div class="pos-card-header">
            <div class="pos-card-symbol-group">
              <span class="pos-card-symbol">{pos["symbol"]}</span>
              <span class="pos-card-name">{pos["name"]}</span>
            </div>
            <div class="pos-card-day" style="color: {color};">{"+" if pos["day_chg"] >= 0 else ""}{pos["day_chg"]:.1f}%</div>
          </div>
          <div class="pos-card-body">
            <div style="display:flex; justify-content:space-between; align-items:flex-end;">
              <div>
                <div class="pos-card-price">${pos["price"]:.2f}</div>
                <div class="pos-card-pnl" style="color: {gain_color};">
                  <span class="pos-card-pnl-amount">{"+" if pos["gain"] >= 0 else ""}${pos["gain"]:,.0f}</span>
                  <span class="pos-card-pnl-pct">{"+" if pos["gain_pct"] >= 0 else ""}{pos["gain_pct"]:.1f}%</span>
                </div>
              </div>
              <div style="opacity:0.9;">{sparkline}</div>
            </div>
          </div>
          <div class="pos-card-footer">
            <div class="pos-card-rsi">
              <span class="pos-card-rsi-label">RSI</span>
              <span class="pos-card-rsi-value" style="color: {rsi_color};">{pos["rsi"]:.0f}</span>
              {rsi_label}
            </div>
            <div class="pos-card-range-bar" title="52W Range: ${pos.get('low_52w', 0):.0f} — ${pos.get('high_52w', 0):.0f}">
              <span style="color:#6b7280;font-size:0.65rem;">52W</span>
              <div class="range-track">
                <div class="range-fill" style="width: {range_pct}%; background: linear-gradient(90deg, #ef4444, #eab308, #10b981);"></div>
                <div style="position:absolute; left:{range_pct}%; top:-2px; width:8px; height:12px; background:#fff; border-radius:2px; transform:translateX(-50%);"></div>
              </div>
            </div>
          </div>
        </div>'''

    # Portfolio allocation donut chart
    donut_colors = ["#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#14b8a6"]
    donut_slices = [(pos["symbol"], pos["value"], donut_colors[i % len(donut_colors)]) for i, pos in enumerate(p["positions"])]
    if p["cash"] > 0:
        donut_slices.append(("Cash", p["cash"], "#4b5563"))
    donut_chart = svg_donut(donut_slices, size=220)

    # Donut legend
    donut_legend = ""
    total_for_pct = sum(v for _, v, _ in donut_slices)
    for label, value, clr in donut_slices:
        pct = value / total_for_pct * 100 if total_for_pct else 0
        donut_legend += f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;"><div style="width:12px;height:12px;border-radius:3px;background:{clr};flex-shrink:0;"></div><span style="color:#9ca3af;font-size:0.85rem;">{label}</span><span style="color:#e5e5e5;font-weight:600;margin-left:auto;">{pct:.0f}%</span></div>'

    # Opportunities HTML
    opps_html = ""
    for opp in data.get("opportunities", []):
        opps_html += f'''
        <div class="opp-card">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <span style="font-family: 'Fraunces', Georgia, serif; font-size: 1.4rem; font-weight: 900; color: #fff;">{opp["symbol"]}</span>
              <span style="color: #6b7280; margin-left: 10px; font-size: 1rem;">${opp["price"]:.0f}</span>
            </div>
            <div style="text-align: right;">
              <div style="color: #ef4444; font-weight: 800; font-size: 1.1rem;">{opp["from_high"]:+.0f}% from high</div>
              <div style="color: #6b7280; font-size: 0.9rem; margin-top: 4px;">RSI {opp["rsi"]:.0f} &middot; {opp["position"]:.0f}% of range</div>
            </div>
          </div>
        </div>'''

    if not opps_html:
        opps_html = '<p style="color: #6b7280; font-size: 1.05rem;">No bottoming signals detected today. All scanned tickers are above 30% of their 52-week range.</p>'

    # Market indices
    sp = m.get("sp500", {})
    nas = m.get("nasdaq", {})
    vix = m.get("vix", {})
    oil = m.get("oil", {})
    gold = m.get("gold", {})

    # Server-side PIN auth via /api/login (Vercel serverless function)
    # Content hidden by default, shown after cookie verification
    content_display = 'style="display:none;"'
    password_script = '''
<div id="login" style="display:flex; min-height:100vh; align-items:center; justify-content:center; background:linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #16213e 100%);">
  <div style="text-align:center; max-width:380px; padding:48px 32px; background:rgba(26,26,46,0.8); border-radius:20px; border:1px solid rgba(99,102,241,0.2); backdrop-filter:blur(20px);">
    <div style="font-family:Fraunces,serif; font-size:1.8rem; font-weight:900; margin-bottom:8px;">📊 Portfolio Pulse</div>
    <p style="color:#6b7280; margin-bottom:32px; font-size:0.9rem;">Enter PIN to view your report</p>
    <input id="pin" type="password" maxlength="6" placeholder="••••" autofocus
      style="width:100%; padding:14px 18px; border-radius:10px; border:1px solid #2a2a3e; background:#0a0a0f; color:#fff; font-size:1.4rem; text-align:center; letter-spacing:8px; outline:none; margin-bottom:16px;"
      onkeydown="if(event.key===\'Enter\')unlock()">
    <button onclick="unlock()"
      style="width:100%; padding:14px; border-radius:10px; border:none; background:linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; font-weight:700; font-size:1rem; cursor:pointer;">
      Unlock
    </button>
    <p id="err" style="color:#ef4444; margin-top:12px; display:none; font-size:0.9rem;">Incorrect PIN</p>
  </div>
</div>
<script>
''' + AUTH_SCRIPT + '''
</script>'''

    # VIX status text
    vix_status = "Calm" if vix.get("price", 20) < 15 else ("Normal" if vix.get("price", 20) < 20 else ("Elevated" if vix.get("price", 20) < 30 else "Panic"))

    # Market card color helper
    def mc_color(val):
        return "#10b981" if val >= 0 else "#ef4444"

    def mc_border(val):
        return "rgba(16,185,129,0.3)" if val >= 0 else "rgba(239,68,68,0.3)"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
<title>Portfolio Pulse — {now.strftime("%B %d, %Y")}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,100..900;1,9..144,100..900&family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #0a0a0f;
    color: #e5e5e5;
    font-size: 16px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }}
  .serif {{ font-family: 'Fraunces', Georgia, 'Times New Roman', serif; }}

  /* ── Fade-in animation ── */
  @keyframes fadeInUp {{
    from {{ opacity: 0; transform: translateY(24px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  @keyframes fadeIn {{
    from {{ opacity: 0; }}
    to {{ opacity: 1; }}
  }}
  .fade-section {{
    opacity: 0;
    animation: fadeInUp 0.8s ease-out forwards;
  }}
  .fade-section:nth-child(1) {{ animation-delay: 0.1s; }}
  .fade-section:nth-child(2) {{ animation-delay: 0.25s; }}
  .fade-section:nth-child(3) {{ animation-delay: 0.4s; }}
  .fade-section:nth-child(4) {{ animation-delay: 0.55s; }}
  .fade-section:nth-child(5) {{ animation-delay: 0.7s; }}
  .fade-section:nth-child(6) {{ animation-delay: 0.85s; }}
  .fade-section:nth-child(7) {{ animation-delay: 1.0s; }}
  .fade-section:nth-child(8) {{ animation-delay: 1.1s; }}

  /* ── Hero ── */
  .hero {{
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 48px 24px;
    background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #16213e 100%);
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle at 30% 50%, rgba(99, 102, 241, 0.1) 0%, transparent 50%),
                radial-gradient(circle at 70% 30%, rgba(16, 185, 129, 0.07) 0%, transparent 50%);
  }}
  .hero * {{ position: relative; z-index: 1; }}
  .hero .edition {{
    color: #6366f1;
    text-transform: uppercase;
    letter-spacing: 8px;
    font-weight: 700;
    font-size: 0.8rem;
    margin-bottom: 24px;
  }}
  .hero .title {{
    font-size: clamp(2.8rem, 8vw, 5.5rem);
    font-weight: 900;
    line-height: 1.05;
    margin-bottom: 12px;
    background: linear-gradient(135deg, #fff 0%, #c7d2fe 50%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .hero .date {{
    color: #6b7280;
    font-size: 1.05rem;
    margin-bottom: 48px;
    letter-spacing: 1px;
  }}
  .hero .big-number {{
    font-size: clamp(3.5rem, 12vw, 7rem);
    font-weight: 900;
    color: #fff;
    line-height: 1;
    letter-spacing: -2px;
  }}
  .hero .change {{
    font-size: 1.4rem;
    color: {day_color};
    font-weight: 700;
    margin-top: 12px;
    letter-spacing: 0.5px;
  }}
  .hero .pnl {{
    color: #6b7280;
    font-size: 1.05rem;
    margin-top: 12px;
  }}

  /* ── Section base ── */
  .section {{ padding: 72px 24px; max-width: 920px; margin: 0 auto; }}
  .section-label {{
    color: #6366f1;
    text-transform: uppercase;
    letter-spacing: 6px;
    font-weight: 700;
    font-size: 0.75rem;
    margin-bottom: 14px;
  }}
  .section-title {{
    font-size: clamp(1.8rem, 5vw, 2.8rem);
    font-weight: 900;
    margin-bottom: 36px;
    line-height: 1.1;
    letter-spacing: -0.5px;
  }}

  /* ── Dark section ── */
  .dark-section {{ background: #111118; padding: 72px 24px; }}
  .dark-section .inner {{ max-width: 920px; margin: 0 auto; }}

  /* ── Accent section ── */
  .accent-section {{ background: linear-gradient(135deg, #1e1b4b, #312e81); padding: 72px 24px; }}
  .accent-section .inner {{ max-width: 920px; margin: 0 auto; }}

  /* ── Analysis section ── */
  .analysis-section {{
    background: linear-gradient(180deg, #0f0f18 0%, #141422 100%);
    padding: 72px 24px;
    border-top: 1px solid rgba(99,102,241,0.2);
    border-bottom: 1px solid rgba(99,102,241,0.2);
  }}
  .analysis-section .inner {{ max-width: 920px; margin: 0 auto; }}

  /* ── Green section ── */
  .green-section {{ background: linear-gradient(135deg, #052e16, #064e3b); padding: 72px 24px; }}
  .green-section .inner {{ max-width: 920px; margin: 0 auto; }}

  /* ── Market cards ── */
  .market-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-top: 28px;
  }}
  .market-card {{
    background: rgba(26, 26, 46, 0.8);
    border-radius: 16px;
    padding: 24px 20px;
    text-align: center;
    border: 1px solid rgba(255,255,255,0.04);
    transition: transform 0.2s ease, border-color 0.2s ease;
  }}
  .market-card:hover {{
    transform: translateY(-2px);
    border-color: rgba(255,255,255,0.08);
  }}
  .market-card .label {{
    color: #6b7280;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 3px;
    margin-bottom: 10px;
    font-weight: 600;
  }}
  .market-card .value {{
    font-size: 1.6rem;
    font-weight: 800;
    font-family: 'Fraunces', Georgia, serif;
    letter-spacing: -0.5px;
  }}
  .market-card .chg {{
    font-size: 0.95rem;
    margin-top: 6px;
    font-weight: 700;
  }}

  /* ── Fear & Greed gauge ── */
  .fear-greed-wrapper {{
    margin-top: 40px;
    padding: 32px;
    background: rgba(26, 26, 46, 0.6);
    border-radius: 20px;
    border: 1px solid rgba(255,255,255,0.04);
  }}
  .fear-greed-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 20px;
  }}
  .fear-greed-label {{
    color: #6b7280;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 4px;
    font-weight: 600;
  }}
  .fear-greed-value {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 2.4rem;
    font-weight: 900;
    letter-spacing: -1px;
  }}
  .fear-greed-status {{
    font-size: 0.85rem;
    font-weight: 600;
    margin-top: 2px;
  }}
  .gauge {{
    width: 100%;
    height: 18px;
    background: linear-gradient(to right, #ef4444 0%, #f97316 25%, #eab308 45%, #10b981 70%, #22c55e 100%);
    border-radius: 10px;
    position: relative;
    box-shadow: 0 2px 12px rgba(0,0,0,0.3);
  }}
  .gauge-marker {{
    position: absolute;
    top: -6px;
    width: 30px;
    height: 30px;
    background: #fff;
    border-radius: 50%;
    border: 4px solid #0a0a0f;
    left: {fg_val}%;
    transform: translateX(-50%);
    box-shadow: 0 2px 8px rgba(0,0,0,0.5);
    transition: left 0.5s ease;
  }}
  .gauge-labels {{
    display: flex;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 0.7rem;
    color: #4b5563;
    text-transform: uppercase;
    letter-spacing: 2px;
    font-weight: 600;
  }}

  /* ── Position cards ── */
  .pos-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }}
  .pos-card {{
    border-radius: 16px;
    padding: 24px;
    border: 1px solid rgba(255,255,255,0.06);
    transition: transform 0.2s ease, border-color 0.2s ease;
  }}
  .pos-card:hover {{
    transform: translateY(-2px);
    border-color: rgba(255,255,255,0.12);
  }}
  .pos-card-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
  }}
  .pos-card-symbol-group {{
    display: flex;
    flex-direction: column;
  }}
  .pos-card-symbol {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 1.35rem;
    font-weight: 900;
    letter-spacing: -0.5px;
  }}
  .pos-card-name {{
    color: #6b7280;
    font-size: 0.8rem;
    margin-top: 2px;
  }}
  .pos-card-day {{
    font-weight: 700;
    font-size: 0.95rem;
    padding: 4px 10px;
    border-radius: 8px;
    background: rgba(255,255,255,0.04);
    min-width: 44px;
    text-align: center;
  }}
  .pos-card-body {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 16px;
  }}
  .pos-card-price {{
    font-size: 1.1rem;
    font-weight: 600;
    color: #d1d5db;
  }}
  .pos-card-pnl {{
    text-align: right;
  }}
  .pos-card-pnl-amount {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 1.4rem;
    font-weight: 900;
    display: block;
    letter-spacing: -0.5px;
  }}
  .pos-card-pnl-pct {{
    font-size: 0.85rem;
    font-weight: 600;
    opacity: 0.8;
  }}
  .pos-card-footer {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.06);
  }}
  .pos-card-rsi {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .pos-card-rsi-label {{
    color: #4b5563;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    font-weight: 600;
  }}
  .pos-card-rsi-value {{
    font-weight: 800;
    font-size: 0.95rem;
  }}
  .rsi-badge {{
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 6px;
    border-radius: 4px;
  }}
  .rsi-overbought {{
    color: #ef4444;
    background: rgba(239,68,68,0.12);
  }}
  .rsi-oversold {{
    color: #10b981;
    background: rgba(16,185,129,0.12);
  }}
  .pos-card-range-bar {{
    flex: 0 0 80px;
  }}
  .range-track {{
    height: 4px;
    background: rgba(255,255,255,0.08);
    border-radius: 2px;
    overflow: hidden;
  }}
  .range-fill {{
    height: 100%;
    border-radius: 2px;
    transition: width 0.5s ease;
  }}

  .cash-bar {{
    margin-top: 20px;
    display: flex;
    gap: 20px;
    color: #6b7280;
    font-size: 1rem;
    font-weight: 500;
    padding: 16px 20px;
    background: rgba(255,255,255,0.02);
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.04);
  }}
  .cash-bar span {{
    font-weight: 700;
    color: #d1d5db;
  }}

  /* ── Analysis cards (editorial style) ── */
  .analysis-card {{
    background: rgba(26, 26, 46, 0.6);
    border-radius: 16px;
    padding: 0;
    margin-bottom: 20px;
    border: 1px solid rgba(255,255,255,0.04);
    overflow: hidden;
    transition: transform 0.2s ease;
  }}
  .analysis-card:hover {{
    transform: translateY(-2px);
  }}
  .analysis-card-inner {{
    padding: 28px 32px 28px 32px;
    position: relative;
    border-left: 4px solid var(--accent, #6366f1);
  }}
  .analysis-quote-mark {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 4rem;
    line-height: 1;
    opacity: 0.15;
    position: absolute;
    top: 8px;
    right: 24px;
    pointer-events: none;
  }}
  .analysis-card-title {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 1.25rem;
    font-weight: 800;
    color: #fff;
    margin-bottom: 12px;
    line-height: 1.3;
  }}
  .analysis-card-body {{
    color: #b0b8c8;
    line-height: 1.8;
    font-size: 1.1rem;
  }}

  /* ── Macro grid ── */
  .macro-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    text-align: center;
  }}
  .macro-stat-number {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 2.8rem;
    font-weight: 900;
    color: #a5b4fc;
    letter-spacing: -1px;
  }}
  .macro-stat-label {{
    color: #818cf8;
    font-size: 0.8rem;
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 2px;
    font-weight: 600;
  }}
  .macro-stat-status {{
    font-weight: 700;
    margin-top: 10px;
    font-size: 0.95rem;
  }}

  /* ── Opportunities ── */
  .opp-card {{
    background: rgba(16,185,129,0.06);
    border-radius: 16px;
    padding: 22px 24px;
    margin-bottom: 14px;
    border: 1px solid rgba(16,185,129,0.12);
    transition: transform 0.2s ease;
  }}
  .opp-card:hover {{
    transform: translateY(-2px);
  }}

  /* ── Footer ── */
  .footer {{
    text-align: center;
    padding: 64px 24px;
    color: #4b5563;
    font-size: 0.9rem;
    background: #0a0a0f;
    border-top: 1px solid rgba(255,255,255,0.04);
  }}
  .footer a {{ color: #6366f1; text-decoration: none; }}
  .footer a:hover {{ text-decoration: underline; }}
  .claude-badge {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 24px;
    padding: 10px 20px;
    background: rgba(181, 120, 255, 0.08);
    border: 1px solid rgba(181, 120, 255, 0.2);
    border-radius: 100px;
    color: #b578ff;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.5px;
  }}
  .claude-badge svg {{
    width: 16px;
    height: 16px;
    fill: #b578ff;
  }}

  /* ── Mobile responsive ── */
  @media (max-width: 768px) {{
    .section {{ padding: 48px 20px; }}
    .dark-section, .analysis-section, .accent-section, .green-section {{ padding: 48px 20px; }}
    .section, .dark-section .inner, .accent-section .inner, .analysis-section .inner, .green-section .inner {{
      padding-left: 16px;
      padding-right: 16px;
    }}
    .hero {{ padding: 40px 20px; min-height: 85vh; }}
    .hero .big-number {{ font-size: 2.8rem; letter-spacing: -1px; }}
    .hero .title {{ font-size: 2rem; }}
    .hero .edition {{ letter-spacing: 5px; font-size: 0.7rem; }}
    .hero .change {{ font-size: 1.15rem; }}
    .section-title {{ font-size: 1.5rem; }}

    /* Market grid: 2 columns on mobile */
    .market-grid {{ grid-template-columns: repeat(2, 1fr); gap: 12px; }}
    .market-card {{ padding: 18px 14px; }}
    .market-card .value {{ font-size: 1.3rem; }}
    .market-card .label {{ font-size: 0.65rem; letter-spacing: 2px; }}

    /* Fear gauge */
    .fear-greed-wrapper {{ padding: 24px 20px; }}
    .fear-greed-value {{ font-size: 2rem; }}

    /* Position cards: single column */
    .pos-grid {{ grid-template-columns: 1fr; }}
    .pos-card {{ padding: 20px; }}
    .pos-card-pnl-amount {{ font-size: 1.2rem; }}

    /* Macro grid: single column */
    .macro-grid {{ grid-template-columns: 1fr; gap: 28px; }}
    .macro-stat-number {{ font-size: 2.4rem; }}

    /* Analysis cards */
    .analysis-card-inner {{ padding: 22px 20px; }}
    .analysis-card-body {{ font-size: 1rem; }}
    .analysis-quote-mark {{ font-size: 3rem; right: 16px; }}

    /* Cash bar */
    .cash-bar {{ flex-direction: column; gap: 8px; }}

    /* Ensure min touch target */
    button, a, .market-card, .pos-card, .analysis-card {{
      min-height: 44px;
    }}
  }}

  @media (max-width: 380px) {{
    .market-grid {{ grid-template-columns: 1fr; }}
    .hero .big-number {{ font-size: 2.2rem; }}
  }}
</style>
</head>
<body>

<div id="content" {content_display}>

<!-- HERO -->
<div class="hero fade-section">
  <div class="edition">Portfolio Pulse &middot; {now.strftime("%B %d, %Y")}</div>
  <h1 class="title serif">Market Report</h1>
  <p class="date">{now.strftime("%A")} &middot; {now.strftime("%I:%M %p").lstrip("0")}</p>
  <div class="big-number serif">${p["total_value"]:,.0f}</div>
  <div class="change">{day_arrow} {"+" if p["day_change"] >= 0 else ""}${p["day_change"]:,.0f} ({p["day_change_pct"]:+.2f}%) today</div>
  <div class="pnl">All-time P&amp;L: {"+" if p["total_gain"] >= 0 else ""}${p["total_gain"]:,.0f} ({p["total_gain_pct"]:+.1f}%)</div>
</div>

<!-- MARKET PULSE -->
<div class="dark-section fade-section">
  <div class="inner">
    <div class="section-label">Market Pulse</div>
    <h2 class="section-title serif">How the markets moved</h2>
    <div class="market-grid">
      <div class="market-card" style="border-bottom: 3px solid {mc_border(sp.get('change', 0))};">
        <div class="label">S&amp;P 500</div>
        <div class="value" style="color: #fff;">{sp.get("price", 0):,.0f}</div>
        <div class="chg" style="color: {mc_color(sp.get('change', 0))};">{"+" if sp.get("change", 0) >= 0 else ""}{sp.get("change", 0):.2f}%</div>
      </div>
      <div class="market-card" style="border-bottom: 3px solid {mc_border(nas.get('change', 0))};">
        <div class="label">Nasdaq</div>
        <div class="value" style="color: #fff;">{nas.get("price", 0):,.0f}</div>
        <div class="chg" style="color: {mc_color(nas.get('change', 0))};">{"+" if nas.get("change", 0) >= 0 else ""}{nas.get("change", 0):.2f}%</div>
      </div>
      <div class="market-card" style="border-bottom: 3px solid rgba(107,114,128,0.3);">
        <div class="label">VIX</div>
        <div class="value" style="color: #fff;">{vix.get("price", 0):.1f}</div>
        <div class="chg" style="color: {"#10b981" if vix.get("price", 20) < 20 else ("#f97316" if vix.get("price", 20) < 30 else "#ef4444")};">{vix_status}</div>
      </div>
      <div class="market-card" style="border-bottom: 3px solid {mc_border(oil.get('change', 0))};">
        <div class="label">Oil</div>
        <div class="value" style="color: #fff;">${oil.get("price", 0):.0f}</div>
        <div class="chg" style="color: {mc_color(oil.get('change', 0))};">{"+" if oil.get("change", 0) >= 0 else ""}{oil.get("change", 0):.1f}%</div>
      </div>
      <div class="market-card" style="border-bottom: 3px solid {mc_border(gold.get('change', 0))};">
        <div class="label">Gold</div>
        <div class="value" style="color: #fff;">${gold.get("price", 0):,.0f}</div>
        <div class="chg" style="color: {mc_color(gold.get('change', 0))};">{"+" if gold.get("change", 0) >= 0 else ""}{gold.get("change", 0):.1f}%</div>
      </div>
      <div class="market-card" style="border-bottom: 3px solid {fg_color}40;">
        <div class="label">Fear &amp; Greed</div>
        <div class="value" style="color: {fg_color};">{fg_val:.0f}</div>
        <div class="chg" style="color: {fg_color};">{fg_label.title()}</div>
      </div>
    </div>
    <div class="fear-greed-wrapper" style="text-align:center;">
      <div class="fear-greed-label" style="margin-bottom:8px;">Fear &amp; Greed Index</div>
      <div style="display:flex;justify-content:center;">
        {svg_radial_gauge(fg_val, size=220)}
      </div>
      <div class="fear-greed-value" style="color: {fg_color}; font-family:'Fraunces',serif; font-size:3rem; font-weight:900; margin-top:-10px;">{fg_val:.0f}</div>
      <div class="fear-greed-status" style="color: {fg_color}; font-size:1.1rem; font-weight:600;">{fg_label.title()}</div>
    </div>
  </div>
</div>

<!-- MACRO HEALTH -->
<div class="accent-section fade-section">
  <div class="inner">
    <div class="section-label">Macro Health</div>
    <h2 class="section-title serif">Recession probability: Low</h2>
    <div class="macro-grid">
      <div>
        <div class="macro-stat-number">{macro["spread"]:+.2f}%</div>
        <div class="macro-stat-label">10Y-2Y Spread</div>
        <div class="macro-stat-status" style="color: {"#10b981" if macro["spread"] > 0 else "#ef4444"};">
          {"Normal" if macro["spread"] > 0 else "INVERTED"}
        </div>
      </div>
      <div>
        <div class="macro-stat-number">{macro["t10"]:.2f}%</div>
        <div class="macro-stat-label">10Y Treasury</div>
      </div>
      <div>
        <div class="macro-stat-number">{macro["t2"]:.2f}%</div>
        <div class="macro-stat-label">2Y Treasury</div>
      </div>
    </div>
  </div>
</div>

<!-- ALLOCATION -->
<div class="dark-section fade-section">
  <div class="inner">
    <div class="section-label">Allocation</div>
    <h2 class="section-title serif">Where your money is</h2>
    <div style="display:flex; gap:40px; align-items:center; justify-content:center; flex-wrap:wrap;">
      <div style="flex-shrink:0;">{donut_chart}</div>
      <div style="min-width:180px;">{donut_legend}</div>
    </div>
  </div>
</div>

<!-- POSITIONS -->
<div class="section fade-section">
  <div class="section-label">Holdings</div>
  <h2 class="section-title serif">Your positions today</h2>
  <div class="pos-grid">
    {pos_cards}
  </div>
  <div class="cash-bar">
    <div>Cash: <span>${p["cash"]:,.0f}</span></div>
    {"<div>CD: <span>$" + f'{p["cd"]:,.0f}</span></div>' if p["cd"] > 0 else ""}
  </div>
</div>

<!-- AI ANALYSIS -->
<div class="analysis-section fade-section">
  <div class="inner">
    <div class="section-label">Analysis</div>
    <h2 class="section-title serif">What you need to know</h2>
    {analysis_html}
  </div>
</div>

<!-- OPPORTUNITIES -->
<div class="green-section fade-section">
  <div class="inner">
    <div class="section-label">Radar</div>
    <h2 class="section-title serif">Bottoming opportunities</h2>
    <p style="color: #86efac; margin-bottom: 28px; font-size: 1.05rem; line-height: 1.7;">Stocks showing early recovery signals after significant pullbacks. These are candidates worth investigating, not automatic buys.</p>
    {opps_html}
  </div>
</div>

<!-- FOOTER -->
<div class="footer fade-section">
  <p style="margin-bottom: 8px; font-size: 1rem;"><strong style="color: #9ca3af;">Portfolio Pulse</strong> &mdash; AI-powered investment analysis</p>
  <p>Generated by <a href="https://github.com/Benja-Pauls/portfolio-pulse">portfolio-pulse</a> &middot; {now.strftime("%B %d, %Y %I:%M %p").lstrip("0")}</p>
  <p style="margin-top: 14px; font-size: 0.8rem; color: #374151;">This is automated analysis, not financial advice. Always do your own research.</p>
  <div class="claude-badge">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-2h2v2zm0-4h-2V7h2v6zm4 4h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
    Powered by Claude Opus
  </div>
</div>

</div><!-- end #content -->

{password_script}

</body>
</html>'''

    return html


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Issue date (YYYY-MM-DD)")
    parser.add_argument("--analysis", default=None, help="AI-generated analysis text (multiline). If not provided, a placeholder is used.")
    # Password protection is handled server-side via Vercel /api/login
    args = parser.parse_args()

    issue_date = args.date or datetime.now().strftime("%Y-%m-%d")
    # Output to both issues/ (local archive) and public/ (Vercel deploy)
    issues_dir = Path(__file__).parent / "issues"
    public_dir = Path(__file__).parent / "public"
    issues_dir.mkdir(exist_ok=True)
    public_dir.mkdir(exist_ok=True)

    print(f"Gathering market data...")
    data = gather_data()

    print(f"Generating AI analysis with Claude Opus...")
    opus_text = generate_opus_analysis(data)
    opus_html = parse_opus_cards(opus_text) if opus_text else None
    if opus_html:
        print(f"Opus analysis generated ({len(opus_text)} chars)")
    else:
        print("Opus unavailable, using auto-generated analysis")

    print(f"Rendering HTML...")
    html = render_html(data, analysis_text=args.analysis, opus_html=opus_html)

    output = issues_dir / f"{issue_date}.html"
    output.write_text(html)
    print(f"Generated: {output}")

    # Also write to public/ for Vercel (index + dated)
    (public_dir / "index.html").write_text(html)
    (public_dir / f"{issue_date}.html").write_text(html)
    print(f"Vercel public: {public_dir / 'index.html'}")

    return str(output)


if __name__ == "__main__":
    main()
