"""Agentic Portfolio Pulse composer.

The agent loop here gives Claude two kinds of tools:

  RESEARCH tools — read-only ways to dig deeper before writing
    - run_cli           : run any safe schwab_cli.py subcommand
    - web_search        : Anthropic-hosted web search
    - fetch_earnings    : Finnhub earnings actuals (last 90 days, by symbol)
    - fetch_news        : Finnhub company news (last N days)
    - read_file         : read PRINCIPLES.md or any whitelisted reference file

  ARTICLE-BUILDING tools — structured writes into ArticleStore
    - set_hero_summary
    - add_analysis_card
    - add_opportunity
    - add_position_action
    - set_market_summary
    - finalize_article

The agent loop runs until finalize_article is called or MAX_TURNS is hit.
ArticleStore.render() emits HTML strings matching the existing render_html()
signature (opus_html, opus_opps_html, opus_conclusion_html), so the rest of
generate_issue.py is untouched.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

STOCK_DIR = Path(__file__).parent.parent / "Stock_Portfolio"
PORTFOLIO_PULSE_DIR = Path(__file__).parent

MODEL = "claude-opus-4-7"
MAX_TURNS = 30
MAX_TOKENS_PER_TURN = 8000

# CLI commands the agent is allowed to invoke. Anything that mutates state
# (trade buy/sell, watchlist add, journal log, alerts add, drift set, auth) is
# blocked. The first token of the command is checked against this set.
SAFE_CLI_COMMANDS = {
    "briefing", "research", "news", "sentiment", "analyst", "insider",
    "congress", "fear-greed", "macro", "etf-holdings", "overlap",
    "technicals", "risk", "exposure", "correlation", "monte-carlo", "arima",
    "predict", "portfolio-forecast", "momentum", "opportunities",
    "scan-pullbacks", "detect-bottoms", "price-context", "whales",
    "recession-check", "sector-pulse", "fed-watch", "verify-insider",
    "dividends", "earnings-calendar", "income", "dashboard", "ticker",
    "chart", "heatmap", "leaderboard", "summary", "positions", "balances",
    "quote", "movers", "history", "transactions", "export", "pre-buy",
    "compare", "screener", "tax-impact", "tax-profile", "tax-calc",
    "size-position", "backtest-fear", "backtest-sma", "earnings-guidance",
    "what-if",
}

READABLE_FILES = {"PRINCIPLES.md", "CLAUDE.md"}

# Phrases that mean "I'm punting on this decision" — banned from any card body
# or action detail. The agent's job is to make the call now, not defer.
BANNED_DEFERRAL_PHRASES = (
    "follow up", "follow-up", "monitor", "wait and see", "revisit if",
    "revisit later", "keep an eye", "check back", "tbd", "to be determined",
    "more analysis needed", "we'll see", "stay tuned", "watch closely",
)

REQUIRED_HOLDINGS = ("IVV", "OEF", "GLD", "IAU", "EFV", "BAI", "ISRG", "MSFT", "CASH")


# ---------------------------------------------------------------------------
# ArticleStore — structured representation of the issue, rendered to HTML
# ---------------------------------------------------------------------------

LABEL_COLORS = {
    "POSITION ALERT": "#f59e0b",
    "MARKET SIGNAL": "#6366f1",
    "EARNINGS RESULT": "#8b5cf6",
    "EARNINGS PREVIEW": "#8b5cf6",
    "TAX STRATEGY": "#06b6d4",
    "OPPORTUNITY": "#10b981",
    "RISK WARNING": "#ef4444",
    "MACRO": "#3b82f6",
    "PORTFOLIO": "#ec4899",
    "REBALANCE": "#ec4899",
    "THESIS UPDATE": "#6366f1",
}

VERDICT_COLORS = {"BUY": "#10b981", "WATCH": "#f59e0b", "AVOID": "#ef4444"}

TYPE_CONFIG = {
    "HOLD": ("#6b7280", "—"),
    "BUY":  ("#10b981", "▲"),
    "ADD":  ("#10b981", "+"),
    "SELL": ("#ef4444", "▼"),
    "TRIM": ("#f59e0b", "↓"),
    "WATCH": ("#8b5cf6", "👁"),
    "NO ACTION": ("#6b7280", "—"),
}

URGENCY_CONFIG = {
    "NOW": ("#ef4444", "●"),
    "SOON": ("#f59e0b", "●"),
    "WAIT": ("#6b7280", "○"),
    "NO ACTION": ("#4b5563", "○"),
}


@dataclass
class AnalysisCard:
    icon: str
    label: str
    title: str
    body: str
    sources: list[str]


@dataclass
class Opportunity:
    symbol: str
    headline: str
    analysis: str
    verdict: str
    sources: list[str]


@dataclass
class PositionAction:
    symbol: str
    name: str
    type: str
    detail: str
    urgency: str


@dataclass
class ArticleStore:
    hero_summary: str = ""
    market_summary: str = ""
    analysis_cards: list[AnalysisCard] = field(default_factory=list)
    opportunities: list[Opportunity] = field(default_factory=list)
    actions: list[PositionAction] = field(default_factory=list)
    finalized: bool = False

    def render(self, opp_data: list[dict] | None = None) -> tuple[str, str, str]:
        """Render to (analysis_html, opps_html, conclusion_html) matching the
        signature render_html() expects. opp_data is the bottoming-scan dicts
        from gather_data() so we can attach the visual range bar."""
        opp_data = opp_data or []
        return self._render_analysis(), self._render_opps(opp_data), self._render_conclusion()

    def _render_analysis(self) -> str:
        out = ""
        if self.hero_summary:
            out += f'''
        <div style="background:linear-gradient(135deg, rgba(99,102,241,0.12), rgba(236,72,153,0.06)); border-radius:20px; padding:32px 36px; margin-bottom:32px; border:1px solid rgba(99,102,241,0.25);">
          <div style="font-size:0.7rem; color:#a5b4fc; text-transform:uppercase; letter-spacing:4px; font-weight:700; margin-bottom:14px;">TODAY'S LEDE</div>
          <p style="font-family:'Fraunces',serif; font-size:1.35rem; font-weight:600; color:#f3f4f6; line-height:1.55; margin:0;">{self.hero_summary}</p>
        </div>'''
        for card in self.analysis_cards:
            color = "#6366f1"
            for key, clr in LABEL_COLORS.items():
                if key.lower() in card.label.lower():
                    color = clr
                    break

            sources_html = ""
            if card.sources:
                sources_html = '<div style="margin-top:14px; display:flex; flex-wrap:wrap; gap:6px;">'
                for src in card.sources[:5]:
                    sources_html += (
                        f'<span style="background:rgba(255,255,255,0.06); color:#6b7280; '
                        f'font-size:0.7rem; padding:3px 8px; border-radius:4px; '
                        f'letter-spacing:0.5px;">{src}</span>'
                    )
                sources_html += "</div>"

            label_html = (
                f'<div style="display:inline-flex; align-items:center; gap:6px; '
                f'background:{color}20; color:{color}; font-size:0.7rem; font-weight:700; '
                f'padding:4px 10px; border-radius:4px; letter-spacing:1.5px; '
                f'text-transform:uppercase; margin-bottom:10px;">{card.icon} {card.label}</div>'
            )

            out += f'''
        <div style="background:linear-gradient(135deg, rgba(26,26,46,0.8), rgba(26,26,46,0.4)); border-radius:16px; padding:28px; margin-bottom:20px; border-left:4px solid {color}; backdrop-filter:blur(10px);">
          {label_html}
          <h3 style="font-family:'Fraunces',serif; font-size:1.25rem; font-weight:800; color:#fff; margin-bottom:12px; line-height:1.3;">{card.title}</h3>
          <p style="color:#b0b8c8; line-height:1.8; font-size:1.05rem;">{card.body}</p>
          {sources_html}
        </div>'''
        return out

    def _render_opps(self, opp_data: list[dict]) -> str:
        out = ""
        for i, opp in enumerate(self.opportunities, 1):
            v_color = VERDICT_COLORS.get(opp.verdict.upper(), "#6b7280")
            data = next((o for o in opp_data if o["symbol"] == opp.symbol), None)
            range_w = data["position"] if data else 20
            from_high = data["from_high"] if data else -30
            rsi = data["rsi"] if data else 35
            price = data["price"] if data else 0

            sources_html = ""
            if opp.sources:
                sources_html = '<div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:6px;">'
                for src in opp.sources[:3]:
                    sources_html += (
                        f'<span style="background:rgba(255,255,255,0.06); color:#6b7280; '
                        f'font-size:0.65rem; padding:2px 7px; border-radius:3px;">{src}</span>'
                    )
                sources_html += "</div>"

            out += f'''
        <div style="display:flex; gap:20px; align-items:stretch; margin-bottom:20px; background:linear-gradient(135deg, rgba(16,185,129,0.04), rgba(16,185,129,0.01)); border:1px solid rgba(16,185,129,0.15); border-radius:16px; padding:24px; position:relative; overflow:hidden;">
          <div style="font-family:'Fraunces',serif; font-size:3.5rem; font-weight:900; color:rgba(16,185,129,0.15); line-height:1; flex-shrink:0; width:45px; text-align:center;">{i}</div>
          <div style="flex:1; min-width:0;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; margin-bottom:6px;">
              <div style="font-family:'Fraunces',serif; font-size:1.4rem; font-weight:900; color:#fff;">{opp.symbol} <span style="color:#6b7280; font-size:0.85rem; font-weight:400;">${price:.0f}</span></div>
              <div style="display:inline-flex; align-items:center; gap:4px; background:{v_color}20; color:{v_color}; font-size:0.7rem; font-weight:800; padding:4px 10px; border-radius:4px; letter-spacing:1px;">{opp.verdict.upper()}</div>
            </div>
            <div style="font-weight:600; color:#d1d5db; font-size:0.95rem; margin-bottom:8px;">{opp.headline}</div>
            <p style="color:#9ca3af; line-height:1.7; font-size:0.9rem;">{opp.analysis}</p>
            <div style="margin-top:12px; display:flex; gap:16px; flex-wrap:wrap; align-items:center;">
              <span style="color:#ef4444; font-weight:700; font-size:0.85rem;">{from_high:+.0f}% from high</span>
              <span style="color:#6b7280; font-size:0.8rem;">RSI {rsi:.0f}</span>
              <div style="flex:1; min-width:80px; height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden;">
                <div style="height:100%; width:{range_w}%; background:linear-gradient(90deg, #ef4444, #10b981); border-radius:3px;"></div>
              </div>
            </div>
            {sources_html}
          </div>
        </div>'''
        return out

    def _render_conclusion(self) -> str:
        actions_html = ""
        held_symbols = {"IVV", "OEF", "GLD", "IAU", "EFV", "BAI", "ISRG", "MSFT"}
        for a in self.actions:
            t_color, t_icon = TYPE_CONFIG.get(a.type.upper(), ("#6b7280", "—"))
            u_color, u_dot = URGENCY_CONFIG.get(a.urgency.upper(), ("#6b7280", "○"))
            is_new = a.type.upper() in ("BUY", "WATCH") and a.symbol not in held_symbols
            new_badge = (
                '<span style="background:#10b981; color:#fff; font-size:0.6rem; '
                'padding:2px 6px; border-radius:3px; margin-left:6px; '
                'font-weight:700; letter-spacing:1px;">NEW</span>' if is_new else ""
            )
            actions_html += f'''
        <div style="display:flex; align-items:center; gap:12px; padding:14px 16px; border-bottom:1px solid rgba(255,255,255,0.04);">
          <div style="color:{u_color}; font-size:0.7rem; flex-shrink:0; width:10px;">{u_dot}</div>
          <div style="font-family:'Fraunces',serif; font-weight:800; color:#fff; width:55px; flex-shrink:0;">{a.symbol}</div>
          <div style="display:inline-flex; align-items:center; background:{t_color}18; color:{t_color}; font-size:0.7rem; font-weight:700; padding:3px 8px; border-radius:4px; letter-spacing:1px; flex-shrink:0; min-width:55px; justify-content:center;">{t_icon} {a.type.upper()}</div>
          <div style="color:#9ca3af; font-size:0.9rem; line-height:1.4; flex:1;">{a.detail}{new_badge}</div>
        </div>'''

        if not (self.market_summary or actions_html):
            return ""

        summary_block = ""
        if self.market_summary:
            summary_block = (
                "<div style=\"background:linear-gradient(135deg, #1e1b4b, #312e81); "
                "border-radius:20px; padding:28px; text-align:center; "
                "border:1px solid rgba(99,102,241,0.3); margin-bottom:28px;\">"
                "<div style=\"font-size:0.7rem; color:#818cf8; text-transform:uppercase; "
                "letter-spacing:4px; font-weight:700; margin-bottom:10px;\">Market Summary</div>"
                f"<p style=\"font-family:Fraunces,serif; font-size:1.2rem; font-weight:700; "
                f"color:#e0e7ff; line-height:1.6; max-width:700px; margin:0 auto;\">"
                f"{self.market_summary}</p></div>"
            )

        actions_block = ""
        if actions_html:
            actions_block = (
                "<div style=\"background:rgba(26,26,46,0.6); border-radius:16px; "
                "border:1px solid rgba(255,255,255,0.06); overflow:hidden;\">"
                "<div style=\"padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.06); "
                "display:flex; align-items:center; gap:10px;\">"
                "<span style=\"font-size:0.7rem; color:#818cf8; text-transform:uppercase; "
                "letter-spacing:4px; font-weight:700;\">Action Plan</span>"
                "<div style=\"flex:1; height:1px; background:linear-gradient(90deg, "
                "rgba(99,102,241,0.3), transparent);\"></div></div>"
                f"{actions_html}</div>"
            )

        return f'<div style="margin-top:40px;">{summary_block}{actions_block}</div>'


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

def tool_definitions() -> list[dict]:
    return [
        # ── research tools ───────────────────────────────────────────────
        {
            "name": "run_cli",
            "description": (
                "Run a Stock_Portfolio CLI command and get its text output. "
                "Use this for live portfolio data, technicals, insider activity, "
                "macro signals, recession check, pre-buy due diligence, etc. "
                "Pass the args after `python schwab_cli.py`. Examples: "
                "'pre-buy ISRG', 'insider MSFT --days 30', 'technicals IVV --signals-only', "
                "'recession-check', 'whales --fund berkshire'. Read-only commands only — "
                "trade execution is blocked."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Args to pass to schwab_cli.py, e.g. 'pre-buy ISRG'",
                    }
                },
                "required": ["command"],
            },
        },
        {
            "name": "fetch_earnings",
            "description": (
                "Get the most recent earnings actuals for a ticker from Finnhub: "
                "EPS estimate vs actual (beat/miss), revenue estimate vs actual, "
                "quarter, and report date. Use this whenever a holding had an earnings "
                "report you need to react to."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker e.g. ISRG"},
                    "limit": {"type": "integer", "description": "Most recent N quarters (default 4)"},
                },
                "required": ["symbol"],
            },
        },
        {
            "name": "fetch_news",
            "description": (
                "Get recent company news headlines from Finnhub for a ticker. Use this "
                "for context after a price move or earnings event."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "description": "Lookback window (default 7)"},
                    "limit": {"type": "integer", "description": "Max headlines (default 8)"},
                },
                "required": ["symbol"],
            },
        },
        {
            "name": "read_file",
            "description": (
                "Read a reference file from the Stock_Portfolio directory. "
                f"Allowed files: {sorted(READABLE_FILES)}. Use this to consult "
                "the investment principles when making a recommendation."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "e.g. 'PRINCIPLES.md'"}
                },
                "required": ["filename"],
            },
        },
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 12,
        },
        # ── article-building tools ──────────────────────────────────────
        {
            "name": "set_hero_summary",
            "description": (
                "Set the one-paragraph hero summary at the top of the issue. "
                "Make it editorial — the lede a magazine reader sees first. "
                "2-4 sentences. Reference the day's most important signal."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        {
            "name": "add_analysis_card",
            "description": (
                "Add an editorial analysis card. Each card = one substantive "
                "insight with a clear call to action. Aim for 5-8 cards across "
                "the issue covering: post-earnings reactions, position alerts, "
                "macro signals, opportunities, tax strategy, risk warnings, "
                "thesis updates. Body must reference real numbers and dates and "
                "MUST end with a concrete action — never 'wait and see' or 'monitor'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "icon": {"type": "string", "description": "One emoji"},
                    "label": {
                        "type": "string",
                        "description": (
                            "Category — one of: POSITION ALERT, MARKET SIGNAL, "
                            "EARNINGS RESULT, EARNINGS PREVIEW, TAX STRATEGY, "
                            "OPPORTUNITY, RISK WARNING, MACRO, PORTFOLIO, "
                            "REBALANCE, THESIS UPDATE"
                        ),
                    },
                    "title": {"type": "string", "description": "Punchy editorial headline"},
                    "body": {
                        "type": "string",
                        "description": "3-6 sentences, ends with a concrete action",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1-4 data sources informing the card",
                    },
                },
                "required": ["icon", "label", "title", "body"],
            },
        },
        {
            "name": "add_opportunity",
            "description": (
                "Add a bottoming-opportunity card for a non-portfolio ticker. "
                "Verdict is BUY / WATCH / AVOID. Only call this for tickers that "
                "showed up in the bottoming scan, OR for new ideas you uncovered "
                "via research that genuinely merit consideration."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "headline": {"type": "string"},
                    "analysis": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["BUY", "WATCH", "AVOID"]},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["symbol", "headline", "analysis", "verdict"],
            },
        },
        {
            "name": "add_position_action",
            "description": (
                "Add an action-plan row for a holding (or a brand-new BUY). "
                "EVERY current holding (IVV, OEF, GLD, IAU, EFV, BAI, ISRG, MSFT) "
                "and Cash MUST get exactly one row. You may add 1-3 NEW BUY rows "
                "for new ideas. Detail must be specific (numbers, dates) and must "
                "be a decision the reader can act on today — no 'revisit later'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["HOLD", "BUY", "ADD", "SELL", "TRIM", "WATCH", "NO ACTION"],
                    },
                    "detail": {"type": "string"},
                    "urgency": {
                        "type": "string",
                        "enum": ["NOW", "SOON", "WAIT", "NO ACTION"],
                    },
                },
                "required": ["symbol", "name", "type", "detail", "urgency"],
            },
        },
        {
            "name": "set_market_summary",
            "description": (
                "Set the 2-3 sentence summary banner at the bottom of the issue "
                "summarizing today's market posture and portfolio health."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        {
            "name": "finalize_article",
            "description": (
                "Call this only when the article is complete: hero summary set, "
                "5+ analysis cards added, every holding has a position action, "
                "market summary set. The agent loop ends after this call."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
    ]


# ---------------------------------------------------------------------------
# Live Schwab positions (used by gather_data() in generate_issue.py)
# ---------------------------------------------------------------------------

def fetch_live_schwab_positions() -> tuple[list[dict] | None, float, float, float, str | None]:
    """Run `schwab_cli.py export` and parse positions + cash + CD + total.
    Returns (positions, cash, cd, liquidation_value, error_message).
    Positions is None on failure.

    cash folds in money-market sweeps (SWVXX). cd is the FIXED_INCOME bond/CD
    book value. liquidation_value is Schwab's authoritative total — use it as
    the portfolio's total_value rather than recomputing from parts.

    Each position dict: {symbol, name, shares, cost (basis), purchase_date}.
    Bonds/CDs are NOT in `positions` (their CUSIPs aren't priceable via yfinance);
    they're surfaced via `cd` instead.
    """
    err = lambda msg: (None, 0.0, 0.0, 0.0, msg)
    venv_py = STOCK_DIR / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else "python"
    try:
        result = subprocess.run(
            [py, "schwab_cli.py", "export"],
            cwd=str(STOCK_DIR),
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return err("schwab export timed out (likely OAuth browser flow)")
    combined = (result.stdout or "") + (result.stderr or "")
    if "browser-assisted login" in combined.lower() or "oauth/authorize" in combined.lower():
        return err("Schwab OAuth expired — run `python schwab_cli.py auth`")
    if result.returncode != 0:
        return err(f"schwab export exit {result.returncode}: {result.stderr.strip()[:200]}")
    try:
        # Schwab export prints headers from rich; the actual JSON is the trailing
        # JSON object. Find the first '{' that begins a balanced object.
        text = result.stdout
        start = text.find("{")
        if start < 0:
            return err("no JSON in schwab export output")
        payload = json.loads(text[start:])
    except Exception as e:
        return err(f"json parse failed: {e}")

    acct = payload.get("account", {}) or {}
    balances = acct.get("currentBalances", {}) or {}
    cash = float(balances.get("cashBalance", 0) or 0)
    money_market = float(balances.get("moneyMarketFund", 0) or 0)
    total_cash = cash + money_market
    cd_value = float(balances.get("bondValue", 0) or 0)
    liquidation_value = float(balances.get("liquidationValue", 0) or 0)

    positions: list[dict] = []
    for pos in acct.get("positions", []) or []:
        inst = pos.get("instrument", {}) or {}
        symbol = inst.get("symbol")
        if not symbol:
            continue
        asset_type = inst.get("assetType")
        # Skip the money market sweep and any non-equity oddities
        if symbol in {"MMDA1", "MMDA2", "SWVXX"} or asset_type == "CASH_EQUIVALENT":
            # SWVXX is money market — fold its value into cash for the prompt
            if symbol == "SWVXX":
                total_cash += float(pos.get("marketValue", 0) or 0)
            continue
        # Bonds/CDs: bondValue from balances is authoritative; skip the CUSIP-keyed
        # row so it doesn't get fed to yfinance (which can't price CUSIPs).
        if asset_type == "FIXED_INCOME":
            continue
        qty = float(pos.get("longQuantity", 0) or 0)
        if qty == 0:
            continue
        market_value = float(pos.get("marketValue", 0) or 0)
        gain = pos.get("longOpenProfitLoss")
        avg_price = pos.get("averagePrice")
        if gain is not None:
            cost = market_value - float(gain)
        elif avg_price:
            cost = float(avg_price) * qty
        else:
            cost = market_value
        positions.append({
            "symbol": symbol,
            "name": inst.get("description") or symbol,
            "shares": qty,
            "cost": cost,
            "purchase_date": None,  # caller backfills from hardcoded if available
        })

    if not positions:
        return err("no positions in schwab export (account empty?)")
    return positions, total_cash, cd_value, liquidation_value, None


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _run_cli(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"ERROR: could not parse command: {e}"
    if not parts:
        return "ERROR: empty command"
    head = parts[0]
    if head not in SAFE_CLI_COMMANDS:
        return (
            f"ERROR: command '{head}' is not on the read-only allowlist. "
            f"Allowed: {sorted(SAFE_CLI_COMMANDS)}"
        )
    venv_py = STOCK_DIR / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else "python"
    try:
        result = subprocess.run(
            [py, "schwab_cli.py", *parts],
            cwd=str(STOCK_DIR),
            capture_output=True,
            text=True,
            timeout=90,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return (
            f"ERROR: '{head}' timed out after 90s. This usually means the command "
            "is trying to refresh expired Schwab OAuth (interactive browser flow). "
            "Pick a different command — anything that doesn't touch the Schwab "
            "broker API (technicals, news, insider, recession-check, whales, "
            "predict, opportunities, etc.) will work fine."
        )
    out = (result.stdout or "") + (("\n[stderr]\n" + result.stderr) if result.stderr.strip() else "")
    if "browser-assisted login" in out.lower() or "oauth/authorize" in out.lower():
        return (
            f"ERROR: '{head}' requires Schwab OAuth which has expired. The portfolio "
            "data block in the system prompt already contains every position. For "
            "broker-API-only data, work from that. For market data, use "
            "technicals / news / insider / fetch_earnings / web_search instead."
        )
    if len(out) > 12000:
        out = out[:12000] + "\n…[truncated]"
    return out or "(no output)"


def _fetch_earnings(symbol: str, limit: int = 4) -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return "ERROR: FINNHUB_API_KEY not configured"
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/stock/earnings",
            params={"symbol": symbol.upper(), "token": key},
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json()[:limit]
    except Exception as e:
        return f"ERROR: {e}"
    if not rows:
        return f"No earnings actuals found for {symbol}."
    lines = [f"Recent earnings for {symbol.upper()} (most recent first):"]
    for row in rows:
        period = row.get("period", "?")
        actual = row.get("actual")
        estimate = row.get("estimate")
        surprise_pct = row.get("surprisePercent")
        beat_miss = "BEAT" if (surprise_pct or 0) > 0 else ("MISS" if (surprise_pct or 0) < 0 else "INLINE")
        lines.append(
            f"  {period} (Q{row.get('quarter','?')} {row.get('year','?')}): "
            f"EPS actual ${actual} vs est ${estimate} → {beat_miss} "
            f"({surprise_pct:+.1f}%)" if surprise_pct is not None else
            f"  {period}: EPS actual ${actual} vs est ${estimate}"
        )
    return "\n".join(lines)


def _fetch_news(symbol: str, days: int = 7, limit: int = 8) -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return "ERROR: FINNHUB_API_KEY not configured"
    from datetime import timedelta
    today = datetime.now().date()
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol.upper(),
                "from": (today - timedelta(days=days)).isoformat(),
                "to": today.isoformat(),
                "token": key,
            },
            timeout=15,
        )
        r.raise_for_status()
        items = r.json()[:limit]
    except Exception as e:
        return f"ERROR: {e}"
    if not items:
        return f"No news in last {days} days for {symbol}."
    lines = [f"Recent news for {symbol.upper()} (last {days} days):"]
    for it in items:
        ts = datetime.fromtimestamp(it.get("datetime", 0)).strftime("%Y-%m-%d")
        headline = it.get("headline", "")
        source = it.get("source", "")
        lines.append(f"  [{ts}] ({source}) {headline}")
    return "\n".join(lines)


def _read_file(filename: str) -> str:
    if filename not in READABLE_FILES:
        return f"ERROR: '{filename}' not on whitelist {sorted(READABLE_FILES)}"
    p = STOCK_DIR / filename
    if not p.exists():
        return f"ERROR: {p} does not exist"
    text = p.read_text()
    return text[:15000] + ("\n…[truncated]" if len(text) > 15000 else "")


def _check_completeness(store: ArticleStore) -> list[str]:
    """Return a list of human-readable problems blocking finalization, or [] if clean."""
    problems: list[str] = []
    if not store.hero_summary:
        problems.append("hero_summary is empty — call set_hero_summary")
    if not store.market_summary:
        problems.append("market_summary is empty — call set_market_summary")
    if len(store.analysis_cards) < 5:
        problems.append(
            f"only {len(store.analysis_cards)} analysis cards — need at least 5 covering "
            "earnings reactions, position alerts, macro, opportunities, tax/strategy"
        )

    seen_actions = {a.symbol.upper() for a in store.actions}
    missing = [s for s in REQUIRED_HOLDINGS if s not in seen_actions]
    if missing:
        problems.append(
            f"missing add_position_action for: {missing}. EVERY holding plus CASH must have one row."
        )

    def _scan(text: str, where: str) -> None:
        low = text.lower()
        for phrase in BANNED_DEFERRAL_PHRASES:
            if phrase in low:
                problems.append(
                    f"banned deferral phrase '{phrase}' in {where} — rewrite that section "
                    "with a concrete decision (use tools to gather more data if needed)"
                )

    for i, c in enumerate(store.analysis_cards, 1):
        _scan(c.body, f"analysis card #{i} ({c.title!r})")
    for a in store.actions:
        _scan(a.detail, f"action row for {a.symbol}")
    _scan(store.hero_summary, "hero_summary")
    _scan(store.market_summary, "market_summary")
    return problems


def execute_tool(name: str, args: dict, store: ArticleStore) -> str:
    """Dispatch a tool call. Returns the string content for the tool_result block."""
    if name == "run_cli":
        return _run_cli(args["command"])
    if name == "fetch_earnings":
        return _fetch_earnings(args["symbol"], args.get("limit", 4))
    if name == "fetch_news":
        return _fetch_news(args["symbol"], args.get("days", 7), args.get("limit", 8))
    if name == "read_file":
        return _read_file(args["filename"])

    if name == "set_hero_summary":
        store.hero_summary = args["text"].strip()
        return "ok — hero summary set"
    if name == "add_analysis_card":
        store.analysis_cards.append(AnalysisCard(
            icon=args.get("icon", "•"),
            label=args.get("label", "MARKET SIGNAL"),
            title=args["title"],
            body=args["body"],
            sources=args.get("sources", []) or [],
        ))
        return f"ok — analysis card #{len(store.analysis_cards)} added"
    if name == "add_opportunity":
        store.opportunities.append(Opportunity(
            symbol=args["symbol"].upper(),
            headline=args["headline"],
            analysis=args["analysis"],
            verdict=args["verdict"].upper(),
            sources=args.get("sources", []) or [],
        ))
        return f"ok — opportunity {args['symbol']} added"
    if name == "add_position_action":
        store.actions.append(PositionAction(
            symbol=args["symbol"].upper(),
            name=args["name"],
            type=args["type"],
            detail=args["detail"],
            urgency=args["urgency"],
        ))
        return f"ok — action for {args['symbol']} added"
    if name == "set_market_summary":
        store.market_summary = args["text"].strip()
        return "ok — market summary set"
    if name == "finalize_article":
        problems = _check_completeness(store)
        if problems:
            return (
                "REJECTED — finalize_article cannot succeed yet. Fix these gaps "
                "first, then call finalize_article again:\n  - "
                + "\n  - ".join(problems)
            )
        store.finalized = True
        return "ok — article finalized"

    return f"ERROR: unknown tool {name}"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _tax_status(purchase_date: str | None, today_d) -> str:
    """Return a short string like 'short-term, LT in 187 days (2026-10-29)' or
    'long-term (held 412 days)'."""
    if not purchase_date:
        return "tax basis date unknown"
    try:
        pd = datetime.strptime(purchase_date, "%Y-%m-%d").date()
    except ValueError:
        return f"tax basis date unparseable: {purchase_date}"
    held = (today_d - pd).days
    lt_date = pd.replace(year=pd.year + 1)
    days_to_lt = (lt_date - today_d).days
    if days_to_lt <= 0:
        return f"long-term (held {held} days, eligible since {lt_date.isoformat()})"
    return f"short-term (held {held} days, becomes long-term in {days_to_lt} days on {lt_date.isoformat()})"


def build_system_prompt(data: dict) -> str:
    today_dt = datetime.now()
    today = today_dt.strftime("%A, %B %d, %Y")
    today_d = today_dt.date()
    p = data["portfolio"]
    m = data["market"]
    macro = data["macro"]

    positions_summary = "\n".join(
        f"- {pos['symbol']} ({pos['name']}): ${pos['price']:.2f}, "
        f"day {pos['day_chg']:+.1f}%, total P&L {pos['gain']:+,.0f} "
        f"({pos['gain_pct']:+.1f}%), RSI {pos['rsi']:.0f}, "
        f"at {pos.get('range_pos', 0):.0f}% of 52W range, "
        f"{_tax_status(pos.get('purchase_date'), today_d)}"
        for pos in p["positions"]
    )

    source = p.get("source", "hardcoded")
    source_note = p.get("source_note", "")
    source_warning = ""
    if source != "schwab_live":
        source_warning = (
            f"\n⚠️  PORTFOLIO DATA IS NOT LIVE FROM SCHWAB. Source: {source} ({source_note}). "
            "If Ben has traded recently, the share counts and cash below may be wrong. "
            "Note this in the article so the reader knows.\n"
        )

    fg = m.get("fear_greed", {})
    sp = m.get("sp500", {})
    vix = m.get("vix", {})

    opps = data.get("opportunities", [])
    opps_str = "\n".join(
        f"- {o['symbol']}: ${o['price']:.0f}, {o['from_high']:+.0f}% from high, RSI {o['rsi']:.0f}"
        for o in opps
    ) or "  (none detected)"

    earnings_block = ""
    recent_earnings = data.get("recent_earnings", [])
    upcoming_earnings = data.get("upcoming_earnings", [])
    if recent_earnings:
        earnings_block += "\nRECENT EARNINGS REPORTS (HISTORICAL EVENTS — NOT FORECASTS):\n"
        for e in recent_earnings:
            earnings_block += (
                f"  {e['symbol']} reported {e['date']} (Q{e.get('quarter','?')} {e.get('year','?')}): "
                f"EPS actual ${e.get('actual')} vs est ${e.get('estimate')} "
                f"({e.get('surprise_pct', 0):+.1f}%) — stock since report: {e.get('reaction_pct', 0):+.1f}%\n"
            )
    if upcoming_earnings:
        earnings_block += "\nUPCOMING EARNINGS (still in the future as of today):\n"
        for e in upcoming_earnings:
            earnings_block += f"  {e['symbol']} reports {e['date']}\n"

    predictions = data.get("predictions", [])
    pred_str = "\n".join(
        f"  - {p['title']}: {p['probability']:.0f}% Yes (${p['volume']:,.0f} volume)"
        for p in predictions[:8]
    ) or "  (none)"

    # Prior calls — turn this into an ongoing newsletter, not point-in-time analysis
    try:
        from decision_journal import load_recent_decisions, render_grading_block, price_snapshot_from_data
        prior_decisions = load_recent_decisions(days=7)
        grading_block = render_grading_block(
            prior_decisions, price_snapshot_from_data(data), today_d
        )
    except Exception as e:
        grading_block = f"\n(decision_journal unavailable: {e})\n"

    return f"""You are the senior portfolio analyst writing today's edition of Portfolio Pulse, an editorial-style market briefing.

TODAY IS {today}. Treat any date earlier than today as PAST. If a holding had an earnings report in the past few days, that is a HISTORICAL EVENT — go look up what the actual numbers were and react to them. Never write about a past date as if it's still upcoming.

THE READER:
Ben — self-directed investor, ~$307K portfolio at Charles Schwab, Wisconsin single filer, 24% federal bracket. He reads ONE thing per day: this article. He will not "follow up", will not "monitor", will not "check back". Whatever decision needs to be made, you must make it here, with the data you can pull right now.

ABSOLUTE RULES:
1. NO DEFERRAL LANGUAGE. Banned phrases: "follow up", "monitor", "watch for", "wait and see", "revisit if", "keep an eye on", "check back", "TBD", "more analysis needed". If you feel the urge to write one of these, STOP and use a tool to get the answer instead, then make the call.
2. EVERY analysis card body must end with a concrete action — what specifically Ben should do.
3. EVERY current holding (IVV, OEF, GLD, IAU, EFV, BAI, ISRG, MSFT) plus Cash MUST get exactly one add_position_action call. Skipping a holding is a failure.
4. NEVER let short-term tax cost alone be the reason to hold. Tax is one input, not a veto. Decision tree:
   - Thesis intact AND no clearly better opportunity → hold (tax deferral is a bonus, not the reason)
   - Thesis broken OR a clearly superior opportunity exists → SELL even at the short-term rate. The after-tax outcome of cutting a deteriorating position beats riding it down to "save tax".
   - Use tax as a TIE-BREAKER between roughly equivalent options, never as a trump card.
5. POST-EARNINGS REACTIONS ARE THE HIGHEST-PRIORITY CONTENT. If a holding reported in the last 14 days, you MUST: (a) call fetch_earnings to confirm the actuals, (b) call fetch_news to read the reaction, (c) write a dedicated analysis card with label "EARNINGS RESULT", (d) make a clear hold/trim/sell call in that holding's action row.
6. USE YOUR TOOLS. You have run_cli (60+ portfolio commands), fetch_earnings, fetch_news, web_search, read_file. The single most common failure mode is writing from priors instead of pulling fresh data. If you're uncertain about a price, an insider trade, an analyst target, or what the market did today — look it up.
7. GRADE YOUR PAST CALLS. The PRIOR CALLS block (if present) shows what you (the previous edition's analyst) recommended in the last 7 days, plus where the price has moved since. Your FIRST analysis card must be labeled "THESIS UPDATE" or "PORTFOLIO" with title like "Last week's calls — what aged well, what didn't" and grade them honestly. If a HOLD has dropped 5%+, admit you should have called the trim. If a BUY went down, own it. If a SELL went down, take credit. This is a newsletter — you are the same analyst across editions, not a fresh one each day.

WORKFLOW:
1. Skim the data block below.
2. Pull anything else you need: pre-buy checks, post-earnings actuals, web search for catalysts, recession-check, insider activity, etc. Lean toward MORE research, not less.
3. Build the article via the article tools: set_hero_summary → 5-8 add_analysis_card calls → 1-3 add_opportunity calls → one add_position_action per holding+cash → set_market_summary → finalize_article.
4. Call finalize_article when done. The loop ends there.

INVESTMENT FRAMEWORK: Read PRINCIPLES.md early via read_file('PRINCIPLES.md'). Buffett/Munger/Dalio principles. Greedy when others fearful, fearful when greedy. Never sell on a single signal. Patience is the default — but patience is not paralysis when the data calls for action.

TAX MATH (for context, not a rulebook):
- SHORT-TERM (held < 1 year): 30.3% combined fed+WI rate
- LONG-TERM (held > 1 year): 19.4% combined
- Each position's exact short-term/long-term status is shown inline in the PORTFOLIO block below — use those numbers, don't guess from year names.
{source_warning}
PORTFOLIO ({p['total_value']:,.0f} total, {p['day_change_pct']:+.2f}% today, source: {source}):
{positions_summary}
Cash: ${p['cash']:,.0f}   CD: ${p.get('cd', 0):,.0f}

MARKET:
- S&P 500: {sp.get('price', 0):,.0f} ({sp.get('change', 0):+.2f}%)
- VIX: {vix.get('price', 0):.1f}
- Fear & Greed: {fg.get('value', 50):.0f} ({fg.get('label', 'neutral')})
- Yield Curve (10Y-2Y): {macro['spread']:+.2f}% ({macro.get('curve_status', 'Unknown')})
- 10Y Treasury: {macro['t10']:.2f}%
{earnings_block}
PREDICTION MARKETS (Polymarket real money):
{pred_str}

BOTTOMING SCAN (non-portfolio tickers showing oversold + low-in-range):
{opps_str}
{grading_block}"""


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def compose_article(data: dict, *, verbose: bool = True) -> ArticleStore:
    """Run the agent loop. Returns the ArticleStore (may be empty if the API
    key is missing or the loop fails — caller should fall back accordingly)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    store = ArticleStore()
    if not api_key:
        if verbose:
            print("[agent_compose] ANTHROPIC_API_KEY missing — skipping agent loop")
        return store

    try:
        import anthropic
    except ImportError:
        if verbose:
            print("[agent_compose] anthropic SDK not installed")
        return store

    client = anthropic.Anthropic(api_key=api_key)
    system_text = build_system_prompt(data)
    tools = tool_definitions()
    # Mark the last tool with cache_control so the prompt cache covers system+tools
    # together (the cache breakpoint includes everything up to and including the
    # marked block). System prompt must be a list-of-blocks form to also cache it.
    tools_cached = [dict(t) for t in tools]
    tools_cached[-1] = {**tools_cached[-1], "cache_control": {"type": "ephemeral"}}
    system_cached = [{
        "type": "text",
        "text": system_text,
        "cache_control": {"type": "ephemeral"},
    }]

    messages: list[dict] = [{
        "role": "user",
        "content": (
            "Generate today's Portfolio Pulse issue. Pull whatever fresh data you "
            "need first, then build the article via the article-tools. Call "
            "finalize_article when complete."
        ),
    }]

    cache_stats = {"reads": 0, "writes": 0}

    for turn in range(MAX_TURNS):
        if verbose:
            print(f"[agent_compose] turn {turn + 1}/{MAX_TURNS}")
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS_PER_TURN,
                system=system_cached,
                tools=tools_cached,
                messages=messages,
            )
            usage = resp.usage
            cache_stats["reads"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_stats["writes"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        except Exception as e:
            if verbose:
                print(f"[agent_compose] API error on turn {turn + 1}: {e}")
            break

        # Append the assistant turn verbatim so the next request has full context.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            if verbose:
                print(f"[agent_compose] stop_reason={resp.stop_reason} on turn {turn + 1} — exiting loop")
            break

        # Execute every client-side tool_use block in this turn.
        tool_results: list[dict] = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            # Server-side tools (web_search) are executed by Anthropic and the
            # results come back already attached — we just skip them here.
            if block.name == "web_search":
                continue
            try:
                result_text = execute_tool(block.name, block.input or {}, store)
            except Exception as e:
                result_text = f"ERROR executing {block.name}: {e}"
            if verbose:
                preview = result_text[:120].replace("\n", " ")
                print(f"  → {block.name}({json.dumps(block.input)[:80]}): {preview}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        if not tool_results:
            # The model only used server-side tools this turn. Continue so it
            # can read the search results and act on them.
            continue

        messages.append({"role": "user", "content": tool_results})

        if store.finalized:
            if verbose:
                print("[agent_compose] finalize_article called — done")
            break

    if verbose:
        print(
            f"[agent_compose] result: hero={'set' if store.hero_summary else 'EMPTY'}, "
            f"cards={len(store.analysis_cards)}, opps={len(store.opportunities)}, "
            f"actions={len(store.actions)}, finalized={store.finalized}"
        )
        print(
            f"[agent_compose] cache: read={cache_stats['reads']:,} tok, "
            f"wrote={cache_stats['writes']:,} tok"
        )
    return store
