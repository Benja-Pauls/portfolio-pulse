module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const body = req.body || {};
  const pin = String(body.pin || '').trim();
  const correctPin = String(process.env.PORTFOLIO_PIN || '').trim();

  if (!correctPin) {
    return res.status(500).json({ error: 'PIN not configured' });
  }

  if (pin && pin === correctPin) {
    res.setHeader('Set-Cookie', `pp_auth=1; Path=/; Secure; SameSite=Strict; Max-Age=${60 * 60 * 24 * 30}`);
    return res.status(200).json({ ok: true });
  }

  return res.status(401).json({ error: 'Incorrect PIN' });
};
