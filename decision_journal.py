"""Decision journal: persist each issue's recommendations and grade past calls.

The agent treats each daily issue as part of an ongoing newsletter rather than
a one-off snapshot. After it finalizes an article, every position action is
appended to data/decisions.jsonl, plus the day's portfolio thesis to
data/thesis.jsonl. On the next run:
  - The prior week's calls are re-scored against today's prices
  - Each call is reconciled against the *actual* Schwab share count, so the
    agent knows whether the user followed the advice
  - The prior thesis is loaded so today's agent can grade it adversarially

The agent is forbidden from defending its prior calls — see ADVERSARIAL
GRADING in the system prompt. Decisions are data, not positions.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_compose import ArticleStore

JOURNAL_PATH = Path(__file__).parent / "data" / "decisions.jsonl"
THESIS_PATH = Path(__file__).parent / "data" / "thesis.jsonl"
JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)


def append_decisions(
    issue_date: str,
    store: "ArticleStore",
    price_snapshot: dict[str, float],
    shares_snapshot: dict[str, float] | None = None,
) -> int:
    """Append today's actions to the journal. Returns the number of records.

    price_snapshot:  {symbol -> current price at recommendation time}
    shares_snapshot: {symbol -> share count at recommendation time}

    shares_at_call is the critical field for execution-detection on the next
    run. If a future BUY/ADD recommendation hasn't moved the share count,
    the next agent will see "USER DID NOT ACT" instead of assuming execution.
    """
    shares_snapshot = shares_snapshot or {}
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
                "conviction": getattr(action, "conviction", "MEDIUM").upper(),
                "detail": action.detail,
                "price_at_call": price_snapshot.get(sym),
                "shares_at_call": shares_snapshot.get(sym),
            }
            f.write(json.dumps(record) + "\n")
            n += 1
    return n


def append_thesis(issue_date: str, thesis_text: str) -> None:
    """Persist today's portfolio thesis so future editions can grade it."""
    if not thesis_text:
        return
    ts = datetime.now().isoformat(timespec="seconds")
    with THESIS_PATH.open("a") as f:
        f.write(json.dumps({"ts": ts, "issue_date": issue_date, "thesis": thesis_text}) + "\n")


def load_last_thesis() -> dict | None:
    """Return the most recent persisted thesis record, or None if file is empty/missing."""
    if not THESIS_PATH.exists():
        return None
    last = None
    with THESIS_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


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


def render_grading_block(
    decisions: list[dict],
    current_prices: dict[str, float],
    today: date,
    current_shares: dict[str, float] | None = None,
) -> str:
    """Render past decisions vs current prices/shares as a system-prompt block.

    Critically: for each BUY/ADD/SELL/TRIM, compares the share count at
    recommendation time to the current share count. If unchanged, surfaces
    USER DID NOT ACT so the agent doesn't write "today's buy executed".

    Empty string if no decisions yet (first-ever run).
    """
    if not decisions:
        return ""

    current_shares = current_shares or {}

    by_date: dict[str, list[dict]] = {}
    for rec in decisions:
        by_date.setdefault(rec["issue_date"], []).append(rec)

    lines = [
        "",
        "PRIOR RECOMMENDATIONS (last 7 days — these were ANALYST CALLS, not trades).",
        "Reconcile each against the Schwab share counts in the PORTFOLIO block.",
        "Apply ADVERSARIAL grading: write the strongest case the call was WRONG before",
        "deciding whether to defend or reverse it.",
    ]
    for issue_date in sorted(by_date.keys()):
        days_ago = (today - datetime.fromisoformat(issue_date).date()).days
        when = "today" if days_ago == 0 else (f"{days_ago}d ago" if days_ago > 0 else "future?")
        lines.append(f"\n  Issue {issue_date} ({when}):")
        for rec in by_date[issue_date]:
            sym = rec["symbol"]
            cur_price = current_prices.get(sym)
            then_price = rec.get("price_at_call")
            move = ""
            grade_hint = ""
            if cur_price is not None and then_price:
                pct = (cur_price / then_price - 1) * 100
                move = f"  →  now ${cur_price:.2f} ({pct:+.1f}% since call)"
                t = rec["type"]
                if t in ("BUY", "ADD"):
                    grade_hint = "  [BUY/ADD aging well]" if pct > 0 else "  [BUY/ADD against you]"
                elif t in ("SELL", "TRIM"):
                    grade_hint = "  [SELL/TRIM aged well]" if pct < 0 else "  [SELL/TRIM against you]"
                elif t == "HOLD":
                    if abs(pct) > 5:
                        grade_hint = f"  [HOLD: stock moved {pct:+.1f}% — was hold the right call?]"

            # Execution check: did the share count actually move?
            execution_note = ""
            prior_shares = rec.get("shares_at_call")
            cur_sh = current_shares.get(sym)
            if (
                rec["type"] in ("BUY", "ADD", "SELL", "TRIM")
                and prior_shares is not None
                and cur_sh is not None
            ):
                if abs(float(prior_shares) - float(cur_sh)) < 0.5:
                    execution_note = "  [USER DID NOT ACT — share count unchanged]"
                else:
                    delta = float(cur_sh) - float(prior_shares)
                    execution_note = f"  [shares: {float(prior_shares):.0f} → {float(cur_sh):.0f} ({delta:+.0f}) — USER ACTED]"

            conviction = rec.get("conviction", "?")
            then_str = f"@${then_price:.2f}" if then_price is not None else "@?"
            lines.append(
                f"    {sym} {rec['type']:5} (urg: {rec['urgency']}, conv: {conviction}) — "
                f"{then_str}{move}{grade_hint}{execution_note}"
            )
            detail = rec["detail"][:140] + ("…" if len(rec["detail"]) > 140 else "")
            lines.append(f"      reasoning: {detail}")
    lines.append("")
    return "\n".join(lines)


def render_thesis_block(prior_thesis: dict | None, today: date) -> str:
    """Render the most recent persisted thesis as a system-prompt block.
    The agent must grade this thesis adversarially in the current edition."""
    if not prior_thesis:
        return ""
    try:
        d = datetime.fromisoformat(prior_thesis["issue_date"]).date()
        days_ago = (today - d).days
        when = "today" if days_ago == 0 else f"{days_ago}d ago"
    except (KeyError, ValueError):
        when = "previously"
    return (
        f"\nPRIOR PORTFOLIO THESIS (set {when} — grade adversarially. "
        f"What's still true? What's broken? Set a new thesis at the end of this issue):\n"
        f"  \"{prior_thesis.get('thesis', '').strip()}\"\n"
    )


def price_snapshot_from_data(data: dict) -> dict[str, float]:
    """Pull current prices for held positions from the gather_data() dict."""
    snap: dict[str, float] = {}
    for pos in data.get("portfolio", {}).get("positions", []):
        snap[pos["symbol"].upper()] = float(pos["price"])
    return snap


def shares_snapshot_from_data(data: dict) -> dict[str, float]:
    """Pull current share counts (and cash dollars) for non-execution detection."""
    snap: dict[str, float] = {}
    for pos in data.get("portfolio", {}).get("positions", []):
        snap[pos["symbol"].upper()] = float(pos["shares"])
    # CASH gets dollars, not shares — consistent enough for the unchanged-vs-changed check
    snap["CASH"] = float(data.get("portfolio", {}).get("cash", 0) or 0)
    return snap
