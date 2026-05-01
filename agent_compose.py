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

# Phrases that imply a TRADE WAS EXECUTED. The agent issues recommendations
# only — it has no trade authority. Past-tense narrative voice about trades
# is a hallucination that misleads the reader into thinking they (or the
# system) acted. Always frame as "I recommended X" / "the [date] call was Y".
BANNED_EXECUTION_PHRASES = (
    "we bought", "we added", "we sold", "we trimmed", "we executed",
    "today's buy executed", "today's add executed", "today's sell executed",
    "today's trim executed", "today's buys executed", "today's adds executed",
    "the position was trimmed", "the position was added", "the position was sold",
    "the position was bought", "executed cleanly", "executed into",
    "the trade went through", "the buy executed", "the sell executed",
    "the add executed", "the trim executed", "i bought", "i added", "i sold",
    "i trimmed", "the order filled", "filled at",
)

REQUIRED_HOLDINGS = ("IVV", "OEF", "GLD", "IAU", "EFV", "BAI", "ISRG", "MSFT", "CASH")

# Validation regexes for action-row quality
import re as _re
_NUMERIC_QTY = _re.compile(r"\$[\d,]+(?:\.\d+)?|\d+\s*shares?\b|\d+(?:\.\d+)?\s*%")
_TAX_DOLLAR = _re.compile(
    r"\$[\d,]+\s*(?:tax|after.?tax)|tax.{0,15}\$[\d,]+|after.?tax.{0,15}\$[\d,]+|"
    r"\d+(?:\.\d+)?\s*%\s*(?:tax|after.?tax)|tax.{0,15}\d+(?:\.\d+)?\s*%",
    _re.I,
)
_DEPLOY_KEYWORDS = ("deploy", "buy ", "buy $", "add to ", "add $", "shift", "rotate into", "into ")
_DEFER_KEYWORDS = (
    "fomc", "fed ", "cpi", "jobs", "election", "earnings", "vix", "vol ",
    "wait until", "post-", "pre-earnings", "rate decision", "fed decision",
)
_QUANTIFY_TYPES = {"BUY", "ADD", "SELL", "TRIM"}
_TAX_TYPES = {"SELL", "TRIM"}

# Subtle hallucination: "the April 30 add at $X" / "the May 1 buy at $Y" / "today's
# trim at $Z" — phrasing that treats a prior RECOMMENDATION as an executed trade
# without using the obvious phrases like "we bought". Rewrite as "the April 30
# recommendation to add" or "the call to add on April 30".
_HALLUCINATED_TRADE_PATTERN = _re.compile(
    r"\bthe\s+(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2}\s+(?:add|buy|trim|sell|exit|swap)\s+(?:at\s+\$|of\s+\d)|"
    r"\b(?:today's|yesterday's)\s+(?:add|buy|trim|sell|exit)\s+(?:at\s+\$|of\s+\d)|"
    r"\b(?:added|bought|trimmed|sold)\s+\d+\s*shares?\s+(?:at|on)",
    _re.I,
)


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

CONVICTION_CONFIG = {
    "HIGH": ("#10b981", "★★★"),
    "MEDIUM": ("#f59e0b", "★★"),
    "LOW": ("#6b7280", "★"),
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
    conviction: str = "MEDIUM"


@dataclass
class ArticleStore:
    hero_summary: str = ""
    market_summary: str = ""
    portfolio_thesis: str = ""
    analysis_cards: list[AnalysisCard] = field(default_factory=list)
    opportunities: list[Opportunity] = field(default_factory=list)
    actions: list[PositionAction] = field(default_factory=list)
    finalized: bool = False
    finalize_attempts: int = 0  # for the safety valve: skip soft validations after 3 retries

    def render(self, opp_data: list[dict] | None = None) -> tuple[str, str, str, str]:
        """Render to (top_moves_html, analysis_html, opps_html, conclusion_html).

        top_moves_html: HIGH-conviction action rows surfaced at the top of the
        article — the "if you only read three things" panel.
        """
        opp_data = opp_data or []
        return (
            self._render_top_moves(),
            self._render_analysis(),
            self._render_opps(opp_data),
            self._render_conclusion(),
        )

    def _render_top_moves(self) -> str:
        """Big, mobile-friendly cards for HIGH-conviction calls only. Renders
        nothing if there are no HIGH calls."""
        high_actions = [a for a in self.actions if a.conviction.upper() == "HIGH"]
        if not high_actions:
            return ""
        cards = ""
        for a in high_actions:
            t_color, t_icon = TYPE_CONFIG.get(a.type.upper(), ("#6b7280", "—"))
            u_color, u_dot = URGENCY_CONFIG.get(a.urgency.upper(), ("#6b7280", "○"))
            # Pull the "Invalidated if[:]" tail off the detail so we can render it visually
            detail = a.detail
            invalidation = ""
            m = _re.search(r"\b(?:Invalidated|Invalidate)\s+if:?\s*", detail, _re.I)
            if m:
                invalidation = detail[m.end():].strip().rstrip(".") + "."
                detail = detail[:m.start()].rstrip(" .—-")
            invalidation_html = (
                f'<div class="topmove-invalidation"><span class="topmove-invalidation-label">'
                f'⚠ Invalidated if</span> {invalidation}</div>' if invalidation else ""
            )
            cards += f'''
        <div class="topmove-card" style="--accent: {t_color};">
          <div class="topmove-head">
            <div class="topmove-symbol-row">
              <span class="topmove-symbol">{a.symbol}</span>
              <span class="topmove-type-badge" style="--badge: {t_color};">{t_icon} {a.type.upper()}</span>
            </div>
            <div class="topmove-urgency" style="color: {u_color};">{u_dot} {a.urgency.upper()}</div>
          </div>
          <div class="topmove-name">{a.name}</div>
          <div class="topmove-detail">{detail}</div>
          {invalidation_html}
        </div>'''
        return f'''
      <div class="topmoves-section">
        <div class="topmoves-label">Today's high-conviction moves</div>
        <div class="topmoves-tagline">If you only act on three things from this issue.</div>
        <div class="topmoves-grid">{cards}</div>
      </div>'''

    def _render_analysis(self) -> str:
        out = ""
        if self.hero_summary:
            out += f'''
        <div style="background:linear-gradient(135deg, rgba(99,102,241,0.12), rgba(236,72,153,0.06)); border-radius:20px; padding:32px 36px; margin-bottom:32px; border:1px solid rgba(99,102,241,0.25);">
          <div style="font-size:0.7rem; color:#a5b4fc; text-transform:uppercase; letter-spacing:4px; font-weight:700; margin-bottom:14px;">TODAY'S LEDE</div>
          <p style="font-family:'Fraunces',serif; font-size:1.35rem; font-weight:600; color:#f3f4f6; line-height:1.55; margin:0;">{self.hero_summary}</p>
        </div>'''
        if self.portfolio_thesis:
            out += f'''
        <div style="background:rgba(16,185,129,0.06); border:1px solid rgba(16,185,129,0.25); border-radius:14px; padding:20px 24px; margin-bottom:28px;">
          <div style="font-size:0.7rem; color:#34d399; text-transform:uppercase; letter-spacing:3px; font-weight:700; margin-bottom:8px;">PORTFOLIO THESIS</div>
          <p style="color:#d1fae5; line-height:1.65; font-size:1.0rem; margin:0;">{self.portfolio_thesis}</p>
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
            c_color, c_stars = CONVICTION_CONFIG.get(a.conviction.upper(), ("#6b7280", "★"))
            is_new = a.type.upper() in ("BUY", "WATCH") and a.symbol not in held_symbols
            new_badge = (
                '<span style="background:#10b981; color:#fff; font-size:0.6rem; '
                'padding:2px 6px; border-radius:3px; margin-left:6px; '
                'font-weight:700; letter-spacing:1px;">NEW</span>' if is_new else ""
            )
            conviction_badge = (
                f'<div title="Conviction: {a.conviction.upper()}" '
                f'style="color:{c_color}; font-size:0.65rem; flex-shrink:0; '
                f'letter-spacing:1px; min-width:32px; text-align:center;">{c_stars}</div>'
            )
            actions_html += f'''
        <div style="display:flex; align-items:center; gap:12px; padding:14px 16px; border-bottom:1px solid rgba(255,255,255,0.04);">
          <div style="color:{u_color}; font-size:0.7rem; flex-shrink:0; width:10px;">{u_dot}</div>
          <div style="font-family:'Fraunces',serif; font-weight:800; color:#fff; width:55px; flex-shrink:0;">{a.symbol}</div>
          <div style="display:inline-flex; align-items:center; background:{t_color}18; color:{t_color}; font-size:0.7rem; font-weight:700; padding:3px 8px; border-radius:4px; letter-spacing:1px; flex-shrink:0; min-width:55px; justify-content:center;">{t_icon} {a.type.upper()}</div>
          {conviction_badge}
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
            "name": "fetch_options_chain",
            "description": (
                "Get the options chain for a ticker — strikes, bid/ask, IV, "
                "volume, OI, plus annualized premium yield on cash-secured. "
                "Use this to evaluate cash-secured puts (paid to wait at your "
                "declared entry) or covered calls (income on overbought "
                "positions). Especially valuable when there is significant "
                "idle cash and a clear lower-entry trigger; "
                "selling a put at that trigger captures premium AND commits "
                "to the buy. Filters to strikes within ±15% of current price."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker e.g. MSFT"},
                    "expiry": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD expiration. Defaults to nearest expiry ≥14 days out.",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["put", "call"],
                        "description": "Defaults to 'put' (cash-secured put income).",
                    },
                },
                "required": ["symbol"],
            },
        },
        {
            "name": "fetch_economic_calendar",
            "description": (
                "Get upcoming major US economic releases (CPI, PCE, jobs, GDP) "
                "and Fed events (FOMC meetings) with exact dates. Use this "
                "BEFORE writing 'wait for FOMC' or 'pre-CPI' phrasing — cite "
                "the actual date so the deployment plan has a real timeline. "
                "Returns next N days, default 30."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Lookforward window. Default 30, max 90.",
                    }
                },
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
                "for new ideas. Detail must be SPECIFIC (numbers, dates) and "
                "QUANTIFIED — every BUY/ADD/SELL/TRIM must include $ amount, "
                "share count, or % of position. Every SELL/TRIM must include the "
                "explicit $ tax cost at current ST/LT status. Conviction is "
                "required and you must use HIGH sparingly — at most 2-3 HIGH "
                "calls per issue. The CASH row, if HOLD, must either propose a "
                "deployment plan ($+ticker+horizon) or name a specific reason "
                "to defer (FOMC/CPI/earnings/vol)."
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
                    "conviction": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW"],
                        "description": (
                            "Honest conviction. HIGH = act today, you'd bet "
                            "real money on this. MEDIUM = lean toward it but "
                            "not urgent. LOW = noise / inertia. Use HIGH "
                            "sparingly (≤2-3 per issue)."
                        ),
                    },
                },
                "required": ["symbol", "name", "type", "detail", "urgency", "conviction"],
            },
        },
        {
            "name": "set_portfolio_thesis",
            "description": (
                "Set the day's PORTFOLIO THESIS — one paragraph (3-5 sentences) "
                "capturing your dominant macro/positioning view that ties the "
                "action plan together. This persists across editions; future "
                "editions will grade it. Be concrete. Examples of good thesis: "
                "'Tilted to large-cap value via OEF/EFV; gold (~16% via GLD/IAU) "
                "sized for inflation stickiness; cash at 22% deployable on any "
                "S&P -3% day.' NOT acceptable: vague platitudes like 'cautiously "
                "optimistic' or 'balanced approach'. Required to call before "
                "finalize_article."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
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


def _fetch_options_chain(symbol: str, expiry: str | None = None, side: str = "put") -> str:
    """Pull options chain for a symbol. Use to evaluate cash-secured puts (income
    while waiting for an entry) or covered calls. Returns formatted strike table
    filtered to within ±15% of current price."""
    try:
        import yfinance as yf
    except ImportError:
        return "ERROR: yfinance not installed"
    sym = symbol.upper()
    t = yf.Ticker(sym)
    expirations = list(t.options)
    if not expirations:
        return f"No options listed for {sym}."
    today = datetime.now().date()
    chosen = None
    if expiry and expiry in expirations:
        chosen = expiry
    if not chosen:
        for e in expirations:
            try:
                d = datetime.strptime(e, "%Y-%m-%d").date()
                if (d - today).days >= 14:
                    chosen = e
                    break
            except ValueError:
                continue
        chosen = chosen or expirations[0]
    try:
        chain = t.option_chain(chosen)
        df = chain.puts if side.lower() == "put" else chain.calls
        h = t.history(period="2d")
        cur_price = float(h["Close"].iloc[-1]) if not h.empty else 0.0
    except Exception as e:
        return f"ERROR fetching options: {e}"
    if cur_price <= 0:
        return f"ERROR: could not get current price for {sym}"
    lo, hi = cur_price * 0.85, cur_price * 1.15
    df = df[(df["strike"] >= lo) & (df["strike"] <= hi)].copy()
    if df.empty:
        return f"No {side}s within ±15% for {sym} expiring {chosen} (current ${cur_price:.2f})."
    df = df.head(20)
    days_to_exp = (datetime.strptime(chosen, "%Y-%m-%d").date() - today).days
    lines = [
        f"{side.upper()} OPTIONS for {sym} (expires {chosen}, {days_to_exp}d out, current ${cur_price:.2f}):",
        f"  {'Strike':>8} | {'Bid':>5} | {'Ask':>5} | {'Last':>5} | {'IV':>5} | {'Vol':>6} | {'OI':>6} | annualized prem on cash-secured",
    ]
    def _safe_float(v):
        try:
            f = float(v)
            return 0.0 if f != f else f  # NaN check
        except (TypeError, ValueError):
            return 0.0
    def _safe_int(v):
        return int(_safe_float(v))
    for _, row in df.iterrows():
        strike = _safe_float(row["strike"])
        bid = _safe_float(row.get("bid"))
        ask = _safe_float(row.get("ask"))
        last = _safe_float(row.get("lastPrice"))
        iv = _safe_float(row.get("impliedVolatility")) * 100
        vol = _safe_int(row.get("volume"))
        oi = _safe_int(row.get("openInterest"))
        # Annualized premium yield on collateral (for puts: collateral = strike × 100)
        # For one contract: premium = mid × 100, collateral = strike × 100
        mid = ((bid + ask) / 2) if bid > 0 and ask > 0 else last
        ann_yield_pct = (mid / strike) * (365 / max(days_to_exp, 1)) * 100 if strike > 0 else 0
        lines.append(
            f"  ${strike:>7.2f} | ${bid:>4.2f} | ${ask:>4.2f} | ${last:>4.2f} | {iv:>4.1f}% | "
            f"{vol:>6} | {oi:>6} | {ann_yield_pct:>5.1f}% APY"
        )
    lines.append(
        "  Note: APY assumes the put expires worthless. If assigned, you own 100 shares "
        f"at strike (collateral was strike × 100 = ${df['strike'].iloc[0] * 100:,.0f} for the lowest-strike row)."
    )
    return "\n".join(lines)


# Manually maintained 2026 economic calendar. Update annually. Times are best-effort
# from Fed schedule, BLS calendar, and BEA — verify against fetch_news for any specific
# event before the agent commits to a deployment plan timed to it.
_ECONOMIC_CALENDAR_2026 = [
    ("2026-05-01", "Jobs Report (NFP) — April", "highest"),
    ("2026-05-06", "FOMC rate decision (May meeting)", "highest"),
    ("2026-05-13", "CPI — April", "highest"),
    ("2026-05-14", "PPI — April", "medium"),
    ("2026-05-15", "Retail Sales — April", "medium"),
    ("2026-05-29", "PCE — April (Fed's preferred inflation gauge)", "high"),
    ("2026-06-05", "Jobs Report (NFP) — May", "highest"),
    ("2026-06-11", "CPI — May", "highest"),
    ("2026-06-17", "FOMC rate decision (June meeting) + SEP/dot plot", "highest"),
    ("2026-06-26", "PCE — May", "high"),
    ("2026-07-02", "Jobs Report (NFP) — June", "highest"),
    ("2026-07-15", "CPI — June", "highest"),
    ("2026-07-29", "FOMC rate decision (July meeting)", "highest"),
    ("2026-07-30", "GDP Q2 advance", "high"),
    ("2026-07-31", "PCE — June", "high"),
    ("2026-09-04", "Jobs Report (NFP) — August", "highest"),
    ("2026-09-11", "CPI — August", "highest"),
    ("2026-09-16", "FOMC rate decision (September meeting) + SEP/dot plot", "highest"),
]


def _fetch_economic_calendar(days_ahead: int = 30) -> str:
    """Return upcoming major US economic releases / Fed events in next N days.
    Use this when proposing a cash-deployment plan or "wait until X" thesis —
    cite the actual date, not a vague 'next FOMC'."""
    today = datetime.now().date()
    upcoming = []
    for ds, name, impact in _ECONOMIC_CALENDAR_2026:
        try:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
            delta = (d - today).days
            if 0 <= delta <= days_ahead:
                upcoming.append((d, delta, name, impact))
        except ValueError:
            continue
    upcoming.sort()
    if not upcoming:
        return f"No major economic events in next {days_ahead} days. Calendar may need refresh; verify via web_search if specific timing matters."
    lines = [f"Upcoming US economic events (next {days_ahead} days, manual schedule — verify if critical):"]
    for d, delta, name, impact in upcoming:
        when = "today" if delta == 0 else (f"tomorrow" if delta == 1 else f"in {delta}d")
        lines.append(f"  {d.isoformat()} ({when}) — {name}  [{impact} impact]")
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
    if not store.portfolio_thesis:
        problems.append(
            "portfolio_thesis is empty — call set_portfolio_thesis with a concrete "
            "3-5 sentence positioning view that future editions can grade"
        )
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

    # Banned-phrase scans (deferral + execution-implying). Skips occurrences in
    # negative or counterfactual/hypothetical contexts. The agent legitimately
    # uses these phrases when (a) negating ("this is NOT a wait-and-see"),
    # (b) writing the bear case ("a bear would say we sold strength"), or
    # (c) running an if-counterfactual ("if Ben had bought, he would now have…").
    _NEGATION_PATTERN = _re.compile(
        r"\b(?:not|never|isn'?t|aren'?t|won'?t|wasn'?t|weren'?t|stop|avoid|"
        r"no\s+longer|no\s+more|would|could|might|may|should|"
        r"would\s+say|would\s+argue|might\s+say|could\s+argue|"
        r"a\s+bear|a\s+bull|a\s+skeptic|argument\s+that|case\s+that|"
        r"if\s+ben|if\s+he|if\s+executed|had\s+followed|had\s+executed)\b"
    )

    def _phrase_is_negated(text_low: str, phrase: str, idx: int) -> bool:
        """True if phrase at idx is preceded (within 80 chars) by negation/modal."""
        preceding = text_low[max(0, idx - 80):idx]
        return bool(_NEGATION_PATTERN.search(preceding))

    def _scan(text: str, where: str, phrases: tuple[str, ...], kind: str) -> None:
        low = text.lower()
        for phrase in phrases:
            i = 0
            while True:
                idx = low.find(phrase, i)
                if idx < 0:
                    break
                if not _phrase_is_negated(low, phrase, idx):
                    if kind == "deferral":
                        problems.append(
                            f"banned deferral phrase '{phrase}' in {where} — rewrite with a "
                            "concrete decision (use tools to gather more data if needed)"
                        )
                    else:  # execution
                        problems.append(
                            f"banned execution phrase '{phrase}' in {where} — you issue "
                            "RECOMMENDATIONS, not trades. The user has not necessarily "
                            "acted. Rephrase as 'I recommended X' or 'the [date] call was Y'."
                        )
                    break  # one complaint per phrase per location
                i = idx + len(phrase)

    for i, c in enumerate(store.analysis_cards, 1):
        _scan(c.body, f"analysis card #{i} ({c.title!r})", BANNED_DEFERRAL_PHRASES, "deferral")
        _scan(c.body, f"analysis card #{i} ({c.title!r})", BANNED_EXECUTION_PHRASES, "execution")
    for a in store.actions:
        _scan(a.detail, f"action row for {a.symbol}", BANNED_DEFERRAL_PHRASES, "deferral")
        _scan(a.detail, f"action row for {a.symbol}", BANNED_EXECUTION_PHRASES, "execution")
    _scan(store.hero_summary, "hero_summary", BANNED_DEFERRAL_PHRASES, "deferral")
    _scan(store.hero_summary, "hero_summary", BANNED_EXECUTION_PHRASES, "execution")
    _scan(store.market_summary, "market_summary", BANNED_DEFERRAL_PHRASES, "deferral")
    _scan(store.market_summary, "market_summary", BANNED_EXECUTION_PHRASES, "execution")
    _scan(store.portfolio_thesis, "portfolio_thesis", BANNED_EXECUTION_PHRASES, "execution")

    # Subtle hallucination — "the [date] add at $X" / "today's buy at $Y"
    # BUT: legitimate prior-call grading (THESIS UPDATE) needs to reference these.
    # Skip the match if surrounding context contains grading/recommendation keywords.
    _GRADING_CONTEXT_KEYWORDS = (
        "recommendation", "recommended", "called for", "advice", "advised",
        "if ben", "if he had", "would have", "had followed", "had executed",
        "did not execute", "did not act", "user did not", "no execution",
        "if executed", "user acted", "did not run", "schwab still shows",
        "share count unchanged", "wasn't executed", "was not executed",
    )

    def _scan_hallucinated_trade(text: str, where: str) -> None:
        text_low = text.lower()
        for m in _HALLUCINATED_TRADE_PATTERN.finditer(text):
            window = text_low[max(0, m.start() - 80):min(len(text_low), m.end() + 80)]
            if any(k in window for k in _GRADING_CONTEXT_KEYWORDS):
                continue
            problems.append(
                f"trade-execution hallucination in {where}: '{m.group(0)}' — that "
                "phrasing treats a prior RECOMMENDATION as an executed trade without "
                "any grading-context cue. Reword as 'the [date] recommendation to add' "
                "or 'if Ben had followed the [date] add' or pair it with 'Schwab still "
                "shows N shares — the prior add did not execute'."
            )
            return  # one complaint per location is enough

    for i, c in enumerate(store.analysis_cards, 1):
        _scan_hallucinated_trade(c.body, f"analysis card #{i} ({c.title!r})")
    for a in store.actions:
        _scan_hallucinated_trade(a.detail, f"action row for {a.symbol}")
    _scan_hallucinated_trade(store.hero_summary, "hero_summary")
    _scan_hallucinated_trade(store.market_summary, "market_summary")
    _scan_hallucinated_trade(store.portfolio_thesis, "portfolio_thesis")

    # Quantification: every BUY/ADD/SELL/TRIM must specify $ / shares / %
    for a in store.actions:
        if a.type.upper() in _QUANTIFY_TYPES and not _NUMERIC_QTY.search(a.detail):
            problems.append(
                f"action for {a.symbol} ({a.type}) is unquantified — include "
                "$ amount, share count, or % of position in the detail "
                "(e.g. 'add ~5 shares (~$2,000)' or 'trim 20% of position')."
            )

    # Tax cost in dollars on TRIM/SELL
    for a in store.actions:
        if a.type.upper() in _TAX_TYPES and not _TAX_DOLLAR.search(a.detail):
            problems.append(
                f"action for {a.symbol} ({a.type}) lacks an explicit tax cost — "
                "compute the dollar tax impact at the position's ST/LT rate. "
                "Include phrasing like '~$X tax at ST rate' or 'after-tax $Y'."
            )

    # CASH row substance: deployment plan OR specific defer reason
    cash_action = next((a for a in store.actions if a.symbol.upper() == "CASH"), None)
    if cash_action:
        detail_low = cash_action.detail.lower()
        has_deploy = any(k in detail_low for k in _DEPLOY_KEYWORDS) and bool(_NUMERIC_QTY.search(cash_action.detail))
        has_defer = any(k in detail_low for k in _DEFER_KEYWORDS)
        if not (has_deploy or has_defer):
            problems.append(
                "CASH row lacks substance — with idle cash you must EITHER propose a "
                "deployment plan ($ amount + ticker + horizon, e.g. 'deploy $10K into "
                "EFV over 4 weeks') OR cite a specific near-term reason to defer "
                "(FOMC, CPI, earnings, vol event). 'Hold cash' is not enough."
            )

    # Conviction discipline: 1 ≤ HIGH ≤ 3
    high_count = sum(1 for a in store.actions if a.conviction.upper() == "HIGH")
    if store.actions and high_count == 0:
        problems.append(
            "no HIGH-conviction action rows — you're hedging across the board. "
            "Pick at least one position where you'd genuinely act today and tag it HIGH."
        )
    if high_count > 3:
        problems.append(
            f"{high_count} HIGH-conviction action rows — that's too many. HIGH "
            "means you'd bet your own money; if everything is HIGH then nothing is. "
            "Demote weaker ones to MEDIUM. Keep HIGH at 2-3 max."
        )

    # Devil's advocate: HIGH conviction must include falsification clause
    for a in store.actions:
        if a.conviction.upper() == "HIGH":
            low = a.detail.lower()
            if "invalidated if" not in low and "invalidate if" not in low:
                problems.append(
                    f"HIGH-conviction {a.symbol} action lacks a falsification clause. "
                    "Add one short sentence at the end: 'Invalidated if: [specific observable]' "
                    "(e.g. 'Invalidated if MSFT closes below $385 on volume'). If you can't "
                    "name what would prove this wrong, it isn't HIGH conviction."
                )

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
    if name == "fetch_options_chain":
        return _fetch_options_chain(
            args["symbol"],
            args.get("expiry"),
            args.get("side", "put"),
        )
    if name == "fetch_economic_calendar":
        return _fetch_economic_calendar(min(args.get("days_ahead", 30), 90))

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
        sym = args["symbol"].upper()
        new_action = PositionAction(
            symbol=sym,
            name=args["name"],
            type=args["type"],
            detail=args["detail"],
            urgency=args["urgency"],
            conviction=args.get("conviction", "MEDIUM"),
        )
        # Dedupe by symbol: last write wins. Lets the agent revise without
        # piling up duplicate rows after a finalize_article rejection.
        existing = next((i for i, a in enumerate(store.actions) if a.symbol == sym), None)
        if existing is not None:
            store.actions[existing] = new_action
            return f"ok — action for {sym} REPLACED (conviction={new_action.conviction})"
        store.actions.append(new_action)
        return f"ok — action for {sym} added (conviction={new_action.conviction})"
    if name == "set_market_summary":
        store.market_summary = args["text"].strip()
        return "ok — market summary set"
    if name == "set_portfolio_thesis":
        store.portfolio_thesis = args["text"].strip()
        return "ok — portfolio thesis set"
    if name == "finalize_article":
        store.finalize_attempts += 1
        # Hard problems (always block) vs soft problems (allow through after 3 retries).
        # Hard: missing required fields, missing actions, untrue HIGH-conviction.
        # Soft: phrasing/style nags that the regex might be wrong about.
        all_problems = _check_completeness(store)
        SOFT_PREFIXES = (
            "banned deferral phrase",
            "banned execution phrase",
            "trade-execution hallucination",
        )
        hard = [p for p in all_problems if not any(p.startswith(s) for s in SOFT_PREFIXES)]
        soft = [p for p in all_problems if any(p.startswith(s) for s in SOFT_PREFIXES)]

        # If only soft problems remain after 3 attempts, let it through with a warning.
        # The agent has done its best; the validator was probably wrong about context.
        if hard:
            return (
                "REJECTED — finalize_article cannot succeed yet. Fix these gaps "
                "first, then call finalize_article again:\n  - "
                + "\n  - ".join(all_problems)
            )
        if soft and store.finalize_attempts < 3:
            return (
                f"REJECTED (attempt {store.finalize_attempts}/3) — phrasing issues. "
                "Fix and retry; after 3 attempts the article will pass through anyway "
                "since the validator may be misreading your context:\n  - "
                + "\n  - ".join(soft)
            )
        store.finalized = True
        if soft:
            return (
                f"ok — article finalized after {store.finalize_attempts} attempts "
                f"(safety valve: {len(soft)} soft warnings ignored — review for false positives)"
            )
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
        f"- {pos['symbol']} ({pos['name']}): {pos['shares']:.0f} shares @ ${pos['price']:.2f} "
        f"= ${pos['shares'] * pos['price']:,.0f}, "
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

    # Prior calls + prior thesis — turn this into an ongoing newsletter
    try:
        from decision_journal import (
            load_recent_decisions, render_grading_block,
            price_snapshot_from_data, shares_snapshot_from_data,
            load_last_thesis, render_thesis_block,
        )
        prior_decisions = load_recent_decisions(days=7)
        grading_block = render_grading_block(
            prior_decisions,
            price_snapshot_from_data(data),
            today_d,
            shares_snapshot_from_data(data),
        )
        thesis_block = render_thesis_block(load_last_thesis(), today_d)
    except Exception as e:
        grading_block = f"\n(decision_journal unavailable: {e})\n"
        thesis_block = ""

    kpi = p.get("kpi")
    kpi_block = ""
    if kpi:
        alpha_sign = "ahead" if kpi["alpha_pct"] >= 0 else "behind"
        kpi_block = (
            f"\nPORTFOLIO YTD PERFORMANCE (use these numbers in the THESIS UPDATE card):\n"
            f"  Portfolio: {kpi['ytd_return_pct']:+.2f}% YTD\n"
            f"  S&P 500:   {kpi['sp500_ytd_pct']:+.2f}% YTD\n"
            f"  Alpha:     {kpi['alpha_pct']:+.2f}% ({alpha_sign} the index)\n"
            f"  Sharpe:    {kpi['sharpe']:.2f}\n"
            f"  Max DD:    {kpi['max_dd_pct']:.2f}% (worst peak-to-trough YTD)\n"
        )

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
5. POST-EARNINGS REACTIONS ARE THE HIGHEST-PRIORITY CONTENT. If a holding reported in the last 14 days, you MUST: (a) call fetch_earnings to confirm the actuals, (b) call fetch_news to read the reaction, (c) write a dedicated analysis card with label "EARNINGS RESULT", (d) make a clear hold/trim/sell call in that holding's action row. Same applies in mirror image for UPCOMING earnings within 14 days: pre-position the call before the print.
6. USE YOUR TOOLS. You have run_cli (60+ portfolio commands), fetch_earnings, fetch_news, fetch_options_chain, fetch_economic_calendar, web_search, read_file. The single most common failure mode is writing from priors instead of pulling fresh data. If you're uncertain about a price, an insider trade, an analyst target, or what the market did today — look it up. With significant idle cash, evaluate cash-secured puts via fetch_options_chain — getting paid premium to wait at your declared entry is often dominant over a market-order add. Before any "wait for FOMC/CPI" thesis, call fetch_economic_calendar so the date is concrete.
7. GRADE PAST CALLS ADVERSARIALLY. The PRIOR RECOMMENDATIONS block shows what the previous edition's analyst recommended, plus where the price has moved AND whether the user actually executed (USER DID NOT ACT vs USER ACTED). Your FIRST analysis card must be labeled "THESIS UPDATE" or "PORTFOLIO". For each prior call, before grading, write the strongest case it was WRONG: for every BUY/ADD, what would a bear say? For every HOLD, why should it have been a TRIM? For every SELL/TRIM, was it premature? Then judge which side has the stronger argument given today's data. You have NO EGO invested in prior calls — they are data, not your positions. A different analyst writing tomorrow's edition would happily reverse them; you should have the same freedom. If you find yourself defending a prior call mostly because it was your call, REVERSE it.
8. YOU ISSUE RECOMMENDATIONS, NOT TRADES. You have no trade-execution permission. The user reads the article and decides independently. Past calls are advice that may or may not have been acted on. NEVER write "we bought", "today's buy executed", "the position was trimmed", "we added", "i bought", "executed cleanly" — those describe trades that did not happen. ALSO BANNED is the subtler form: "the April 30 add at $X is +1.4%" or "today's buy at $Y" — same hallucination, different surface. Reword as "the April 30 recommendation to add" or "the call to add on April 30" or "if Ben had followed the April 30 ADD". The Schwab share counts in the PORTFOLIO block are the AUTHORITATIVE record — read those numbers and use them verbatim. NEVER infer a share count from "old position + recommended add"; the recommended add likely did not happen. The PRIOR RECOMMENDATIONS block tags each call USER DID NOT ACT or USER ACTED — read it and respect it. If a record predates execution-tracking and lacks the tag, default to USER DID NOT ACT.
9. QUANTIFY EVERY ACTION. Every BUY/ADD/SELL/TRIM action row must include a $ amount, share count, or % of position in the detail. "Add MSFT" is not enough; "Add ~5 shares (~$2,000)" is. Every SELL/TRIM must compute the explicit dollar tax cost at that position's ST/LT rate ("~$X tax at the 30.3% ST rate" or "after-tax $Y").
10. CASH IS A POSITION. With significant idle cash, the CASH row cannot just say "hold cash". You must EITHER propose a concrete deployment plan ($ amount + ticker + horizon, e.g. "deploy $10K into EFV over 4 weeks on -2% S&P days") OR name a specific near-term reason to defer (FOMC decision in N days, CPI release, earnings event, vol regime). Idle cash without a thesis is the silent expensive default.
11. CONVICTION IS REQUIRED AND HONEST. Each action row carries HIGH/MEDIUM/LOW conviction. HIGH means you'd act today and you'd bet your own money. MEDIUM means lean toward action. LOW means noise. Use HIGH sparingly — at most 2-3 per issue. But you MUST tag at least one action HIGH; if everything is MEDIUM you're hedging instead of leading.
12. SET A PORTFOLIO THESIS. Call set_portfolio_thesis once with a 3-5 sentence concrete positioning view that ties the action plan together. NOT "cautiously optimistic" or "balanced approach"; YES "Tilted to large-cap value via OEF/EFV; 16% gold sized for inflation stickiness; 22% cash deployable on S&P -3% days." This persists across editions; future you will grade it. The PRIOR PORTFOLIO THESIS block (if present) shows what the previous edition committed to — grade it adversarially in the THESIS UPDATE card.
13. SELF-CONSISTENCY. Before calling finalize_article, re-read your cards and action rows. If two cards make contradictory claims (e.g., "rotate to defensives" + "lean into AI capex"), revise. The edition must be internally coherent.
14. DEVIL'S ADVOCATE ON HIGH CONVICTION. Every HIGH-conviction action row must end with one short sentence on what would invalidate the call. Format: "Invalidated if: [specific observable]". Examples: "Invalidated if MSFT closes below $385 on volume" / "Invalidated if Q2 Azure growth comes in below 35%". Forces falsifiability — if you can't write the invalidation condition, the conviction isn't HIGH.
15. WRITE FOR MOBILE FIRST. Ben reads this on his phone in 5 minutes. Lead with the answer, then the reasoning. Each card body: 2-4 punchy sentences max, then the action. Action-row details: under 280 characters when possible. Numbers > adjectives. The first 2 cards must be the most important: (1) THESIS UPDATE grading prior calls + thesis adversarially, (2) the highest-impact decision today (post-earnings reaction, biggest position alert, or the cash deployment).

WORKFLOW:
1. Skim the data block below — including PRIOR RECOMMENDATIONS, PRIOR PORTFOLIO THESIS (if present), recent + UPCOMING earnings.
2. Pull anything else you need: pre-buy checks, post-earnings actuals, web search for catalysts, recession-check, insider activity, etc. Lean toward MORE research, not less.
3. Build the article via the article tools: set_hero_summary → set_portfolio_thesis → 5-8 add_analysis_card calls (FIRST card grades prior calls + thesis adversarially) → 1-3 add_opportunity calls → one add_position_action per holding+cash (with conviction) → set_market_summary → finalize_article.
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
{kpi_block}

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
{thesis_block}{grading_block}"""


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
