# Portfolio Pulse

A daily editorial-style market-analysis magazine generated from Ben's Schwab portfolio
(`~/Documents/Personal/Stock_Portfolio/`). Output is a self-contained HTML page deployed
to Vercel and pinged to Ben's phone via Pushover.

**Sister project**: `~/Documents/Personal/Stock_Portfolio/` — has its own CLAUDE.md with
the full CLI surface (60+ commands), portfolio holdings, tax framework, OAuth tokens,
and the read-only-vs-trading rules. Read that file too.

## Hard rule
**NEVER place trades on Ben's account.** The agent's CLI allowlist in
`agent_compose.SAFE_CLI_COMMANDS` excludes `trade` and `auth`, and articles only contain
text recommendations. The user — not the agent — decides what to act on.

## Architecture

```
generate_issue.py     — entry point. gather_data() → compose_article() → render_html() → write file
agent_compose.py      — Claude Opus 4.7 agent loop with tool use:
                          research tools: run_cli, fetch_earnings, fetch_news, web_search, read_file
                          article-builder tools: set_hero_summary, add_analysis_card,
                              add_opportunity, add_position_action, set_market_summary, finalize_article
                        Also exposes fetch_live_schwab_positions() used by gather_data().
decision_journal.py   — persists each issue's actions to data/decisions.jsonl,
                        loads last 7 days into the next system prompt for grading
api/login.js          — Vercel function for the password gate
public/index.html     — latest issue (overwritten each run)
public/YYYY-MM-DD.html— dated archive
```

## Key behavioral guarantees (added 2026-04-26)

1. **No deferral language.** Banned phrases ("monitor", "follow up", "wait and see",
   "revisit if", "keep an eye", etc.) are scanned by `_check_completeness` in
   `agent_compose.py` and reject `finalize_article` if found. The agent must use tools
   to get the answer instead of punting.

2. **Completeness guard.** Every holding (IVV, OEF, GLD, IAU, EFV, BAI, ISRG, MSFT, CASH)
   must have an `add_position_action`; hero + market summary must be set; ≥5 analysis
   cards required. Enforced programmatically.

3. **Decision journal.** Every issue's actions are appended to `data/decisions.jsonl`.
   The next issue's system prompt loads the last 7 days, re-prices them against current
   market, and demands the agent grades them in its first card ("THESIS UPDATE: Last
   week's calls — what aged well, what didn't").

4. **Prompt caching.** System prompt + tools array carry `cache_control: ephemeral` so
   subsequent turns hit the prompt cache. Prints `cache: read=N tok, wrote=N tok` at
   end of run.

5. **Dynamic tax math.** Each position carries `purchase_date`. The system prompt
   computes per-position long-term-eligibility days dynamically, no hardcoded "Dec 2026".

6. **Live Schwab positions w/ graceful fallback.** `gather_data()` tries
   `fetch_live_schwab_positions()` first (calls `schwab_cli.py export` and parses JSON).
   On any failure (expired OAuth, network) falls back to a hardcoded snapshot and sets
   `data["portfolio"]["source"] = "hardcoded"`. The agent's prompt surfaces a warning
   to the reader when running on stale data.

7. **Schwab OAuth weekly check.** `~/Library/LaunchAgents/com.schwab-token-check.plist`
   runs `Stock_Portfolio/schwab_token_check.py` every Mon + Thu at 8am.
   Pushover-pings Ben when refresh token (7-day TTL) is expiring or expired.

## Schwab OAuth state

Refresh tokens have a 7-day TTL. As of 2026-04-26 the token at
`~/Documents/Personal/Stock_Portfolio/token.json` was last created 2026-04-07 and is
**expired**. To re-authorize:

```
cd ~/Documents/Personal/Stock_Portfolio
python schwab_cli.py auth   # opens browser
```

Until re-auth, generator runs use the hardcoded position snapshot in
`generate_issue.py` (gather_data, ~line 192). The article will visibly note
"PORTFOLIO DATA IS NOT LIVE FROM SCHWAB" in this state.

## Running

```
# Generate today's issue (writes issues/YYYY-MM-DD.html and public/index.html)
cd ~/Documents/Personal/portfolio-pulse
../Stock_Portfolio/.venv/bin/python generate_issue.py

# Specific date
.../python generate_issue.py --date 2026-04-26

# Deploy to prod + send Pushover
bash ~/Documents/Personal/Stock_Portfolio/run_all_pulses.sh
```

Cron is set up via three launchd plists: `com.dailypulse.{morning,midday,evening}.plist`,
firing weekdays at 6am / 12pm / 6pm.

## Dependencies

- `anthropic` SDK (Opus 4.7)
- `yfinance` (live prices, indices, technicals)
- `fear_and_greed` (CNN sentiment)
- `requests` (Polymarket, Finnhub, Pushover)
- API keys live in `~/Documents/Personal/Stock_Portfolio/.env`:
  `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `PUSHOVER_API_TOKEN`, `PUSHOVER_USER_KEY`

## Verifying after edits

```
cd ~/Documents/Personal/portfolio-pulse
../Stock_Portfolio/.venv/bin/python generate_issue.py
```

Watch for:
- `recent earnings: [...]` — Finnhub post-earnings auto-fetch worked
- `schwab live: N holdings, $X cash` OR `schwab live unavailable (...)` — Schwab path
- `[agent_compose] turn N/30` — agent loop progress
- `cache: read=N tok` — prompt caching working (>0 on turn 2+)
- `Wrote N decisions to journal` — journal persistence
- `Generated: issues/YYYY-MM-DD.html` — final write

Inspect output: `grep -E "TODAY'S LEDE|EARNINGS RESULT|monitor|follow up|wait and see" issues/YYYY-MM-DD.html`
The grep should find the lede/earnings labels and find ZERO banned phrases.
