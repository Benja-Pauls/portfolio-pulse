const fs = require('fs');
const path = require('path');
const Anthropic = require('@anthropic-ai/sdk').default;

const MODEL = 'claude-sonnet-4-6';  // good balance of quality and speed for follow-ups
const MAX_TOKENS = 2000;
const MAX_HISTORY_TURNS = 20;       // hard cap to bound cost per session
const MAX_USER_MSG_LEN = 4000;      // hard cap per message

function isAuthed(req) {
  // Same cookie pattern as api/login.js
  const cookie = req.headers.cookie || '';
  return /(?:^|;\s*)pp_auth=1(?:;|$)/.test(cookie);
}

function loadContext() {
  // chat-contexts now live in api/_chat-contexts so Vercel auto-bundles them
  // with this function (no includeFiles config needed).
  const candidates = [
    path.join(__dirname, '_chat-contexts', 'latest.json'),
    path.join(process.cwd(), 'api', '_chat-contexts', 'latest.json'),
    path.join(process.cwd(), '_chat-contexts', 'latest.json'),
  ];
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) {
        return JSON.parse(fs.readFileSync(p, 'utf8'));
      }
    } catch (_) {}
  }
  return null;
}

function buildSystemPrompt(ctx) {
  const a = ctx.article || {};
  const p = ctx.portfolio || {};
  const cards = (a.analysis_cards || []).map(
    (c, i) => `  Card ${i + 1} [${c.label}] "${c.title}": ${c.body}`
  ).join('\n');
  const actions = (a.actions || []).map(
    (x) => `  ${x.symbol} ${x.type} (urg=${x.urgency}, conv=${x.conviction}): ${x.detail}`
  ).join('\n');
  const opps = (a.opportunities || []).map(
    (o) => `  ${o.symbol} (${o.verdict}): ${o.headline} — ${o.analysis}`
  ).join('\n');
  const positions = (p.positions || []).map(
    (pos) => `  ${pos.symbol} (${pos.name}): ${pos.shares} shares @ $${(pos.price || 0).toFixed(2)} = $${((pos.shares || 0) * (pos.price || 0)).toFixed(0)}, P&L ${pos.gain >= 0 ? '+' : ''}$${(pos.gain || 0).toFixed(0)} (${(pos.gain_pct || 0).toFixed(1)}%), RSI ${(pos.rsi || 0).toFixed(0)}`
  ).join('\n');

  const kpi = p.kpi || {};
  const kpiLine = kpi.ytd_return_pct != null
    ? `Portfolio YTD ${kpi.ytd_return_pct.toFixed(2)}% / S&P ${(kpi.sp500_ytd_pct || 0).toFixed(2)}% / alpha ${(kpi.alpha_pct || 0).toFixed(2)}% / Sharpe ${(kpi.sharpe || 0).toFixed(2)} / max DD ${(kpi.max_dd_pct || 0).toFixed(2)}%`
    : '(KPI metrics not computed for this issue)';

  return `You are the same senior portfolio analyst who wrote today's edition of Portfolio Pulse. Ben (the reader) is asking follow-up questions about the article you wrote. You have full context: the article you produced, his current Schwab positions, the market data you analyzed, and the investment framework you use.

ISSUE DATE: ${ctx.issue_date}
GENERATED: ${ctx.generated_at}

═══════════════════════════════════════════
TODAY'S ARTICLE — what you wrote earlier today
═══════════════════════════════════════════

LEDE: ${a.hero_summary || '(none)'}

PORTFOLIO THESIS: ${a.portfolio_thesis || '(none)'}

ANALYSIS CARDS:
${cards || '  (none)'}

ACTION PLAN:
${actions || '  (none)'}

OPPORTUNITIES:
${opps || '  (none)'}

MARKET SUMMARY: ${a.market_summary || '(none)'}

═══════════════════════════════════════════
PORTFOLIO STATE (live from Schwab when generated)
═══════════════════════════════════════════
Total: $${(p.total_value || 0).toLocaleString()}    Cash: $${(p.cash || 0).toLocaleString()}    CD: $${(p.cd || 0).toLocaleString()}
Today: ${(p.day_change_pct || 0).toFixed(2)}%    All-time P&L: ${(p.total_gain || 0) >= 0 ? '+' : ''}$${(p.total_gain || 0).toLocaleString()} (${(p.total_gain_pct || 0).toFixed(1)}%)
KPIs: ${kpiLine}

POSITIONS:
${positions}

═══════════════════════════════════════════
INVESTMENT FRAMEWORK (the system prompt that produced today's article)
═══════════════════════════════════════════
${ctx.system_prompt || '(unavailable)'}

═══════════════════════════════════════════
HOW TO ANSWER FOLLOW-UPS
═══════════════════════════════════════════

- You ARE the analyst who wrote this. Answer in first person about your own reasoning where natural ("I sized the cash row at HIGH because…"). You can disagree with your earlier writing if Ben pushes back with new info — but you don't need to capitulate just because he asks.

- ABSOLUTE RULES still apply (carried forward from the article framework):
  • You issue recommendations, not trades. Never imply Ben acted on a prior call unless you can verify (the Schwab share counts are above).
  • No deferral language ("monitor", "wait and see", "follow up"). Make the call.
  • Quantify recommendations: $ amounts, share counts, % of position, dates.
  • Tax cost in dollars on any TRIM/SELL discussion.
  • Adversarial when asked to defend a call — write the bear case before the defense.

- KEEP IT TIGHT FOR MOBILE. Ben is reading on his phone. 2-4 short paragraphs max unless he explicitly asks for a deep-dive.

- If he asks about something outside the article's scope (e.g., a ticker not in his portfolio), use the existing framework but acknowledge you don't have live data for it without him pulling fresh numbers.`;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }
  if (!isAuthed(req)) {
    return res.status(401).json({ error: 'Auth required — log in via the article first' });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured on the server' });
  }

  const body = req.body || {};
  let messages = Array.isArray(body.messages) ? body.messages : [];

  // Sanitize: only role/content, only last N turns, length-cap content
  messages = messages
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_USER_MSG_LEN) }))
    .slice(-MAX_HISTORY_TURNS);

  if (messages.length === 0 || messages[messages.length - 1].role !== 'user') {
    return res.status(400).json({ error: 'messages must end with a user turn' });
  }

  const ctx = loadContext();
  if (!ctx) {
    return res.status(500).json({
      error: 'No chat context available — was the article generated with the latest pipeline?',
    });
  }

  const system = buildSystemPrompt(ctx);
  const client = new Anthropic({ apiKey });

  try {
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system: [{ type: 'text', text: system, cache_control: { type: 'ephemeral' } }],
      messages,
    });
    const text = (resp.content || [])
      .filter((b) => b.type === 'text')
      .map((b) => b.text)
      .join('\n');
    return res.status(200).json({
      reply: text,
      usage: {
        input_tokens: resp.usage?.input_tokens,
        output_tokens: resp.usage?.output_tokens,
        cache_read: resp.usage?.cache_read_input_tokens,
        cache_write: resp.usage?.cache_creation_input_tokens,
      },
    });
  } catch (err) {
    return res.status(500).json({ error: `Anthropic API error: ${err?.message || err}` });
  }
};
