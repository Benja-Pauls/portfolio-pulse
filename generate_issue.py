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
        <div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid {color};">
          <h3 style="margin-bottom: 10px; font-size: 1.15rem; color: #fff;">{title}</h3>
          <p style="color: #b0b8c8; line-height: 1.7; font-size: 1rem;">{body}</p>
        </div>'''

    return html


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

            enriched.append({
                **p, "price": price, "value": value,
                "day_chg": day_chg, "gain": gain, "gain_pct": gain_pct,
                "rsi": rsi,
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

    # Use Opus-generated analysis if available, fallback to auto-generated
    if opus_html:
        analysis_html = opus_html
    elif analysis_text:
        paragraphs = analysis_text.strip().split("\n\n")
        analysis_html = ""
        for para in paragraphs:
            if para.strip():
                analysis_html += f'<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #6366f1;"><p style="color: #d1d5db; line-height: 1.8; font-size: 1.05rem;">{para.strip()}</p></div>'
    elif not analysis_text:
        # Generate basic analysis from the data
        analysis_parts = []

        # Big movers
        big_movers = [pos for pos in p["positions"] if abs(pos["day_chg"]) > 2]
        if big_movers:
            for bm in big_movers:
                direction = "surged" if bm["day_chg"] > 0 else "dropped"
                analysis_parts.append(
                    f'<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid {"#10b981" if bm["day_chg"] > 0 else "#ef4444"};">'
                    f'<h3 style="margin-bottom: 8px; font-size: 1.2rem;">{bm["symbol"]} {direction} {abs(bm["day_chg"]):.1f}% today</h3>'
                    f'<p style="color: #9ca3af; line-height: 1.6;">Investigate the cause — large single-day moves often signal a news catalyst. Check for earnings surprises, analyst upgrades/downgrades, or sector-wide rotation.</p>'
                    f'</div>')

        # Overbought warnings
        overbought = [pos for pos in p["positions"] if pos["rsi"] > 70]
        if overbought:
            names = ", ".join(pos["symbol"] for pos in overbought)
            analysis_parts.append(
                f'<div style="background: #1a0a0a; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #ef4444;">'
                f'<h3 style="margin-bottom: 8px; font-size: 1.2rem;">⚠️ Overbought Positions: {names}</h3>'
                f'<p style="color: #9ca3af; line-height: 1.6;">RSI above 70 indicates these positions are technically stretched. This doesn\'t mean sell — but it does mean don\'t add more here. Wait for a pullback before increasing exposure. If any of these drop 5-8%, that would be a better entry point.</p>'
                f'</div>')

        # Oversold opportunities
        oversold = [pos for pos in p["positions"] if pos["rsi"] < 30]
        if oversold:
            names = ", ".join(pos["symbol"] for pos in oversold)
            analysis_parts.append(
                f'<div style="background: #0a1a0a; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #10b981;">'
                f'<h3 style="margin-bottom: 8px; font-size: 1.2rem;">🟢 Oversold: {names}</h3>'
                f'<p style="color: #9ca3af; line-height: 1.6;">RSI below 30 suggests these positions are technically oversold — historically a buying opportunity if fundamentals remain intact. Consider adding to these positions if the thesis hasn\'t changed.</p>'
                f'</div>')

        # Market mood commentary
        fg_val = m.get("fear_greed", {}).get("value", 50)
        vix_val = m.get("vix", {}).get("price", 20)
        spread = macro.get("spread", 0)

        if fg_val < 25:
            analysis_parts.append(
                '<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #6366f1;">'
                '<h3 style="margin-bottom: 8px; font-size: 1.2rem;">🔵 Extreme Fear = Opportunity</h3>'
                f'<p style="color: #9ca3af; line-height: 1.6;">Fear &amp; Greed at {fg_val:.0f} — extreme fear. Historical backtest shows buying during extreme fear has a 75% win rate over 3 months with +4.7% average return. If the yield curve is normal ({spread:+.2f}%, it is) and employment is stable, this is historically one of the best times to deploy cash.</p>'
                '</div>')
        elif fg_val > 75:
            analysis_parts.append(
                '<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #f97316;">'
                '<h3 style="margin-bottom: 8px; font-size: 1.2rem;">🟠 Extreme Greed = Caution</h3>'
                f'<p style="color: #9ca3af; line-height: 1.6;">Fear &amp; Greed at {fg_val:.0f} — the market is euphoric. Historically, extreme greed often precedes pullbacks. Not a sell signal, but definitely not the time to deploy new capital aggressively. Patience.</p>'
                '</div>')

        # Yield curve
        if spread < 0:
            analysis_parts.append(
                '<div style="background: #2d1515; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #ef4444;">'
                '<h3 style="margin-bottom: 8px; font-size: 1.2rem;">🚨 Yield Curve INVERTED</h3>'
                f'<p style="color: #9ca3af; line-height: 1.6;">The 10Y-2Y spread is {spread:.2f}%. An inverted yield curve has preceded every US recession in the last 50 years (with a 6-18 month lead time). Consider reducing equity exposure and increasing defensive positions. Run recession-check for the full signal dashboard.</p>'
                '</div>')

        # Cash drag if applicable
        cash_pct = p["cash"] / p["total_value"] * 100 if p["total_value"] else 0
        if cash_pct > 20:
            analysis_parts.append(
                '<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #eab308;">'
                f'<h3 style="margin-bottom: 8px; font-size: 1.2rem;">💵 {cash_pct:.0f}% Cash Position</h3>'
                f'<p style="color: #9ca3af; line-height: 1.6;">Cash at {cash_pct:.0f}% of portfolio earns ~4.2% in money market while the market averages 10-12%. That gap costs approximately ${p["cash"] * 0.07:,.0f}/year in opportunity cost. If recession signals are green and fear is elevated, consider deploying in tranches.</p>'
                '</div>')

        if not analysis_parts:
            analysis_parts.append(
                '<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #10b981;">'
                '<h3 style="margin-bottom: 8px; font-size: 1.2rem;">✅ Portfolio On Track</h3>'
                '<p style="color: #9ca3af; line-height: 1.6;">No major signals or actions needed today. All positions within normal ranges. Continue holding and monitoring.</p>'
                '</div>')

        analysis_html = "\n".join(analysis_parts)
    else:
        # Use provided analysis (from Claude agent)
        paragraphs = analysis_text.strip().split("\n\n")
        analysis_html = ""
        for para in paragraphs:
            if para.strip():
                analysis_html += f'<div style="background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 16px; border-left: 4px solid #6366f1;"><p style="color: #d1d5db; line-height: 1.8; font-size: 1.05rem;">{para.strip()}</p></div>'

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

    # Build positions HTML
    pos_rows = ""
    for pos in p["positions"]:
        color = "#10b981" if pos["day_chg"] >= 0 else "#ef4444"
        gain_color = "#10b981" if pos["gain"] >= 0 else "#ef4444"
        rsi_color = "#ef4444" if pos["rsi"] > 70 else ("#10b981" if pos["rsi"] < 30 else "#6b7280")
        rsi_label = ""
        if pos["rsi"] > 70:
            rsi_label = '<span style="color: #ef4444; font-size: 0.75rem; margin-left: 4px;">OVERBOUGHT</span>'
        elif pos["rsi"] < 30:
            rsi_label = '<span style="color: #10b981; font-size: 0.75rem; margin-left: 4px;">OVERSOLD</span>'

        pos_rows += f'''
        <tr>
          <td style="padding: 12px 16px; font-weight: 700; font-size: 1.1rem;">{pos["symbol"]}</td>
          <td style="padding: 12px 16px; color: #6b7280; font-size: 0.85rem;">{pos["name"]}</td>
          <td style="padding: 12px 16px; text-align: right;">${pos["price"]:.2f}</td>
          <td style="padding: 12px 16px; text-align: right; color: {color};">{"+" if pos["day_chg"] >= 0 else ""}{pos["day_chg"]:.1f}%</td>
          <td style="padding: 12px 16px; text-align: right; color: {gain_color};">{"+" if pos["gain"] >= 0 else ""}${pos["gain"]:,.0f}</td>
          <td style="padding: 12px 16px; text-align: right; color: {gain_color};">{"+" if pos["gain_pct"] >= 0 else ""}{pos["gain_pct"]:.1f}%</td>
          <td style="padding: 12px 16px; text-align: right; color: {rsi_color};">{pos["rsi"]:.0f}{rsi_label}</td>
        </tr>'''

    # Opportunities HTML
    opps_html = ""
    for opp in data.get("opportunities", []):
        opps_html += f'''
        <div style="background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 12px; border-left: 4px solid #10b981;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <span style="font-size: 1.3rem; font-weight: 800; color: #fff;">{opp["symbol"]}</span>
              <span style="color: #6b7280; margin-left: 8px;">${opp["price"]:.0f}</span>
            </div>
            <div style="text-align: right;">
              <div style="color: #ef4444; font-weight: 700;">{opp["from_high"]:+.0f}% from high</div>
              <div style="color: #6b7280; font-size: 0.85rem;">RSI {opp["rsi"]:.0f} · {opp["position"]:.0f}% of range</div>
            </div>
          </div>
        </div>'''

    if not opps_html:
        opps_html = '<p style="color: #6b7280;">No bottoming signals detected today.</p>'

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
function getCookie(n){{return(document.cookie.match(new RegExp("(?:^|;\\\\s*)"+n+"=([^;]*)"))||[])[1]}}
if(getCookie("pp_auth")==="1"){{
  document.addEventListener("DOMContentLoaded",()=>{{
    document.getElementById("login").style.display="none";
    document.getElementById("content").style.display="block";
  }});
}}
async function unlock(){{
  const pin=document.getElementById("pin").value;
  try{{
    const res=await fetch("/api/login",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{pin}})}});
    if(res.ok){{
      document.getElementById("login").style.display="none";
      document.getElementById("content").style.display="block";
    }}else{{
      document.getElementById("err").style.display="block";
      document.getElementById("pin").value="";
      document.getElementById("pin").focus();
    }}
  }}catch(e){{
    // Offline or local file — just show content
    document.getElementById("login").style.display="none";
    document.getElementById("content").style.display="block";
  }}
}}
</script>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Pulse — {now.strftime("%B %d, %Y")}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,100..900;1,9..144,100..900&family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', sans-serif; background: #0a0a0f; color: #e5e5e5; }}
  .serif {{ font-family: 'Fraunces', serif; }}

  /* Hero */
  .hero {{
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 40px 20px;
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
    background: radial-gradient(circle at 30% 50%, rgba(99, 102, 241, 0.08) 0%, transparent 50%),
                radial-gradient(circle at 70% 30%, rgba(16, 185, 129, 0.06) 0%, transparent 50%);
  }}
  .hero * {{ position: relative; z-index: 1; }}
  .hero .edition {{ color: #6366f1; text-transform: uppercase; letter-spacing: 6px; font-weight: 700; font-size: 0.85rem; margin-bottom: 20px; }}
  .hero .title {{ font-size: clamp(3rem, 8vw, 6rem); font-weight: 900; line-height: 1.05; margin-bottom: 16px; background: linear-gradient(135deg, #fff, #a5b4fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .hero .date {{ color: #6b7280; font-size: 1.1rem; margin-bottom: 40px; }}
  .hero .big-number {{ font-size: clamp(4rem, 12vw, 8rem); font-weight: 900; color: #fff; line-height: 1; }}
  .hero .change {{ font-size: 1.5rem; color: {day_color}; font-weight: 700; margin-top: 8px; }}
  .hero .pnl {{ color: #6b7280; font-size: 1rem; margin-top: 12px; }}

  /* Section */
  .section {{ padding: 80px 20px; max-width: 900px; margin: 0 auto; }}
  .section-label {{ color: #6366f1; text-transform: uppercase; letter-spacing: 4px; font-weight: 700; font-size: 0.8rem; margin-bottom: 12px; }}
  .section-title {{ font-size: clamp(2rem, 5vw, 3rem); font-weight: 900; margin-bottom: 32px; line-height: 1.1; }}

  /* Dark section */
  .dark-section {{ background: #111118; padding: 80px 20px; }}
  .dark-section .inner {{ max-width: 900px; margin: 0 auto; }}

  /* Accent section */
  .accent-section {{ background: linear-gradient(135deg, #1e1b4b, #312e81); padding: 80px 20px; }}
  .accent-section .inner {{ max-width: 900px; margin: 0 auto; }}

  /* Rose alert section */
  .alert-section {{ background: linear-gradient(135deg, #1a0a0a, #2d1515); padding: 80px 20px; border-top: 3px solid #ef4444; border-bottom: 3px solid #ef4444; }}
  .alert-section .inner {{ max-width: 900px; margin: 0 auto; }}

  /* Green section */
  .green-section {{ background: linear-gradient(135deg, #052e16, #064e3b); padding: 80px 20px; }}
  .green-section .inner {{ max-width: 900px; margin: 0 auto; }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{ text-align: left; padding: 12px 16px; color: #6b7280; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 2px; border-bottom: 1px solid #2a2a3e; }}
  tbody tr {{ border-bottom: 1px solid #1a1a2e; transition: background 0.2s; }}
  tbody tr:hover {{ background: rgba(99, 102, 241, 0.05); }}

  /* Market cards */
  .market-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-top: 24px; }}
  .market-card {{ background: #1a1a2e; border-radius: 12px; padding: 20px; text-align: center; }}
  .market-card .label {{ color: #6b7280; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 8px; }}
  .market-card .value {{ font-size: 1.5rem; font-weight: 800; }}
  .market-card .chg {{ font-size: 0.9rem; margin-top: 4px; font-weight: 600; }}

  /* Fear gauge */
  .gauge {{ width: 100%; height: 12px; background: linear-gradient(to right, #ef4444, #f97316, #eab308, #10b981, #22c55e); border-radius: 6px; position: relative; margin-top: 16px; }}
  .gauge-marker {{ position: absolute; top: -4px; width: 20px; height: 20px; background: #fff; border-radius: 50%; border: 3px solid #0a0a0f; left: {fg_val}%; transform: translateX(-50%); }}

  /* Footer */
  .footer {{ text-align: center; padding: 60px 20px; color: #4b5563; font-size: 0.85rem; }}
  .footer a {{ color: #6366f1; text-decoration: none; }}

  @media (max-width: 640px) {{
    .section, .dark-section .inner, .accent-section .inner, .alert-section .inner, .green-section .inner {{ padding-left: 16px; padding-right: 16px; }}
    .hero {{ padding: 32px 16px; min-height: 80vh; }}
    .hero .big-number {{ font-size: 3rem; }}
    .hero .title {{ font-size: 2rem; }}
    .section-title {{ font-size: 1.6rem; }}
    table {{ font-size: 0.8rem; display: block; overflow-x: auto; white-space: nowrap; }}
    thead th {{ padding: 8px 10px; font-size: 0.65rem; }}
    tbody td {{ padding: 8px 10px !important; }}
    .market-grid {{ grid-template-columns: repeat(3, 1fr); gap: 10px; }}
    .market-card {{ padding: 14px 10px; }}
    .market-card .value {{ font-size: 1.2rem; }}
    .market-card .label {{ font-size: 0.65rem; }}
    .accent-section div[style*="grid-template-columns: 1fr 1fr 1fr"] {{ display: flex; flex-direction: column; gap: 20px; text-align: center; }}
  }}
</style>
</head>
<body>

<div id="content" {content_display}>

<!-- ═══════ HERO ═══════ -->
<div class="hero">
  <div class="edition">Portfolio Pulse · {now.strftime("%B %d, %Y")}</div>
  <h1 class="title serif">Market Report</h1>
  <p class="date">{now.strftime("%A · %I:%M %p %Z")}</p>
  <div class="big-number serif">${p["total_value"]:,.0f}</div>
  <div class="change">{day_arrow} {"+" if p["day_change"] >= 0 else ""}${p["day_change"]:,.0f} ({p["day_change_pct"]:+.2f}%) today</div>
  <div class="pnl">All-time P&L: {"+" if p["total_gain"] >= 0 else ""}${p["total_gain"]:,.0f} ({p["total_gain_pct"]:+.1f}%)</div>
</div>

<!-- ═══════ MARKET PULSE ═══════ -->
<div class="dark-section">
  <div class="inner">
    <div class="section-label">Market Pulse</div>
    <h2 class="section-title serif">How the markets moved</h2>
    <div class="market-grid">
      <div class="market-card">
        <div class="label">S&P 500</div>
        <div class="value">{sp.get("price", 0):,.0f}</div>
        <div class="chg" style="color: {"#10b981" if sp.get("change", 0) >= 0 else "#ef4444"};">{"+" if sp.get("change", 0) >= 0 else ""}{sp.get("change", 0):.2f}%</div>
      </div>
      <div class="market-card">
        <div class="label">Nasdaq</div>
        <div class="value">{nas.get("price", 0):,.0f}</div>
        <div class="chg" style="color: {"#10b981" if nas.get("change", 0) >= 0 else "#ef4444"};">{"+" if nas.get("change", 0) >= 0 else ""}{nas.get("change", 0):.2f}%</div>
      </div>
      <div class="market-card">
        <div class="label">VIX</div>
        <div class="value">{vix.get("price", 0):.1f}</div>
        <div class="chg" style="color: #6b7280;">{"Calm" if vix.get("price", 20) < 15 else ("Normal" if vix.get("price", 20) < 20 else ("Elevated" if vix.get("price", 20) < 30 else "Panic"))}</div>
      </div>
      <div class="market-card">
        <div class="label">Oil</div>
        <div class="value">${oil.get("price", 0):.0f}</div>
        <div class="chg" style="color: {"#10b981" if oil.get("change", 0) >= 0 else "#ef4444"};">{"+" if oil.get("change", 0) >= 0 else ""}{oil.get("change", 0):.1f}%</div>
      </div>
      <div class="market-card">
        <div class="label">Gold</div>
        <div class="value">${gold.get("price", 0):,.0f}</div>
        <div class="chg" style="color: {"#10b981" if gold.get("change", 0) >= 0 else "#ef4444"};">{"+" if gold.get("change", 0) >= 0 else ""}{gold.get("change", 0):.1f}%</div>
      </div>
      <div class="market-card">
        <div class="label">Fear & Greed</div>
        <div class="value" style="color: {fg_color};">{fg_val:.0f}</div>
        <div class="chg" style="color: {fg_color};">{fg_label.title()}</div>
      </div>
    </div>
    <div style="margin-top: 32px;">
      <div style="color: #6b7280; font-size: 0.85rem; margin-bottom: 8px;">FEAR ← → GREED</div>
      <div class="gauge"><div class="gauge-marker"></div></div>
    </div>
  </div>
</div>

<!-- ═══════ MACRO HEALTH ═══════ -->
<div class="accent-section">
  <div class="inner">
    <div class="section-label">Macro Health</div>
    <h2 class="section-title serif">Recession probability: Low</h2>
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; text-align: center;">
      <div>
        <div style="font-size: 2.5rem; font-weight: 900; color: #a5b4fc;" class="serif">{macro["spread"]:+.2f}%</div>
        <div style="color: #818cf8; font-size: 0.85rem; margin-top: 4px;">10Y-2Y Spread</div>
        <div style="color: {"#10b981" if macro["spread"] > 0 else "#ef4444"}; font-weight: 700; margin-top: 8px;">{"✅ " + macro["curve_status"] if macro["spread"] > 0 else "🚨 " + macro["curve_status"]}</div>
      </div>
      <div>
        <div style="font-size: 2.5rem; font-weight: 900; color: #a5b4fc;" class="serif">{macro["t10"]:.2f}%</div>
        <div style="color: #818cf8; font-size: 0.85rem; margin-top: 4px;">10Y Treasury</div>
      </div>
      <div>
        <div style="font-size: 2.5rem; font-weight: 900; color: #a5b4fc;" class="serif">{macro["t2"]:.2f}%</div>
        <div style="color: #818cf8; font-size: 0.85rem; margin-top: 4px;">2Y Treasury</div>
      </div>
    </div>
  </div>
</div>

<!-- ═══════ POSITIONS ═══════ -->
<div class="section">
  <div class="section-label">Holdings</div>
  <h2 class="section-title serif">Your positions today</h2>
  <div style="overflow-x: auto;">
    <table>
      <thead>
        <tr>
          <th>Symbol</th><th>Name</th><th style="text-align:right;">Price</th>
          <th style="text-align:right;">Day</th><th style="text-align:right;">P&L $</th>
          <th style="text-align:right;">P&L %</th><th style="text-align:right;">RSI</th>
        </tr>
      </thead>
      <tbody>{pos_rows}</tbody>
    </table>
  </div>
  <div style="margin-top: 24px; display: flex; gap: 24px; color: #6b7280;">
    <div>💵 Cash: ${p["cash"]:,.0f}</div>
    {"<div>🏦 CD: $" + f'{p["cd"]:,.0f}</div>' if p["cd"] > 0 else ""}
  </div>
</div>

<!-- ═══════ AI ANALYSIS ═══════ -->
<div class="alert-section">
  <div class="inner">
    <div class="section-label">Analysis</div>
    <h2 class="section-title serif">What you need to know</h2>
    {analysis_html}
  </div>
</div>

<!-- ═══════ OPPORTUNITIES ═══════ -->
<div class="green-section">
  <div class="inner">
    <div class="section-label">Radar</div>
    <h2 class="section-title serif">Bottoming opportunities</h2>
    <p style="color: #86efac; margin-bottom: 24px; font-size: 0.95rem;">Stocks showing early recovery signals after significant pullbacks. These are candidates worth investigating, not automatic buys.</p>
    {opps_html}
  </div>
</div>

<!-- ═══════ FOOTER ═══════ -->
<div class="footer">
  <p style="margin-bottom: 8px;"><strong>Portfolio Pulse</strong> — AI-powered investment analysis</p>
  <p>Generated by <a href="https://github.com/Benja-Pauls/portfolio-pulse">portfolio-pulse</a> · {now.strftime("%B %d, %Y %I:%M %p")}</p>
  <p style="margin-top: 16px; font-size: 0.75rem;">This is automated analysis, not financial advice. Always do your own research.</p>
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
