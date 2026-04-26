"""Decision journal: persist each issue's recommendations and grade past calls.

The agent treats each daily issue as part of an ongoing newsletter rather than
a one-off snapshot. After it finalizes an article, every position action is
appended to data/decisions.jsonl. On the next run, the prior week's calls are
re-scored against today's prices and surfaced to the agent in the system prompt
so it can:
  - Open with a "LAST WEEK'S CALLS" card grading hits and misses honestly
  - Reverse course when the data has moved against a prior call
  - Build conviction from accurate calls instead of starting fresh every day
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_compose import ArticleStore

JOURNAL_PATH = Path(__file__).parent / "data" / "decisions.jsonl"
JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)


def append_decisions(issue_date: str, store: "ArticleStore", price_snapshot: dict[str, float]) -> int:
    """Append today's actions to the journal. price_snapshot is {symbol: price}.
    Returns the number of records written."""
    ts = datetime.now().isoformat(timespec="seconds")
    n = 0
    with JOURNAL_PATH.open("a") as f:
        for action in store.actions:
            sym = action.symbol.upper()
            record = {
                "ts": ts,
                "issue_date": issue_date,
                "symbol": sym,
                "name": action.name,
                "type": action.type.upper(),
                "urgency": action.urgency.upper(),
                "detail": action.detail,
                "price_at_call": price_snapshot.get(sym),
            }
            f.write(json.dumps(record) + "\n")
            n += 1
    return n


def load_recent_decisions(days: int = 7) -> list[dict]:
    """Return decisions from the last N days, oldest-first."""
    if not JOURNAL_PATH.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).date()
    out = []
    with JOURNAL_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                d = datetime.fromisoformat(rec["issue_date"]).date()
            except (KeyError, ValueError):
                continue
            if d >= cutoff:
                out.append(rec)
    return out


def render_grading_block(decisions: list[dict], current_prices: dict[str, float], today: date) -> str:
    """Render past decisions vs current prices as a system-prompt block.
    Empty string if no decisions yet (first-ever run)."""
    if not decisions:
        return ""

    # Group by issue_date so we can show day-over-day evolution
    by_date: dict[str, list[dict]] = {}
    for rec in decisions:
        by_date.setdefault(rec["issue_date"], []).append(rec)

    lines = ["", "PRIOR CALLS (last 7 days — grade these honestly in your first analysis card):"]
    for issue_date in sorted(by_date.keys()):
        days_ago = (today - datetime.fromisoformat(issue_date).date()).days
        when = "today" if days_ago == 0 else (f"{days_ago}d ago" if days_ago > 0 else "future?")
        lines.append(f"\n  Issue {issue_date} ({when}):")
        for rec in by_date[issue_date]:
            sym = rec["symbol"]
            cur = current_prices.get(sym)
            then = rec.get("price_at_call")
            move = ""
            grade_hint = ""
            if cur is not None and then:
                pct = (cur / then - 1) * 100
                move = f"  →  now ${cur:.2f} ({pct:+.1f}% since call)"
                t = rec["type"]
                # Hint at whether the call has aged well; the agent makes the final judgment.
                if t in ("BUY", "ADD"):
                    grade_hint = "  [BUY/ADD aging well]" if pct > 0 else "  [BUY/ADD against you]"
                elif t in ("SELL", "TRIM"):
                    grade_hint = "  [SELL/TRIM aged well]" if pct < 0 else "  [SELL/TRIM against you]"
                elif t == "HOLD":
                    if abs(pct) > 5:
                        grade_hint = f"  [HOLD: stock moved {pct:+.1f}% — was hold the right call?]"
            lines.append(
                f"    {sym} {rec['type']:5} (urg: {rec['urgency']}) — "
                f"@${then:.2f}{move}{grade_hint}"
                if then is not None
                else f"    {sym} {rec['type']:5} (urg: {rec['urgency']}) — price-at-call missing"
            )
            # Show the original detail, truncated, so the agent can recall the reasoning
            detail = rec["detail"][:140] + ("…" if len(rec["detail"]) > 140 else "")
            lines.append(f"      reasoning: {detail}")
    lines.append("")
    return "\n".join(lines)


def price_snapshot_from_data(data: dict) -> dict[str, float]:
    """Pull current prices for held positions from the gather_data() dict."""
    snap: dict[str, float] = {}
    for pos in data.get("portfolio", {}).get("positions", []):
        snap[pos["symbol"].upper()] = float(pos["price"])
    return snap
