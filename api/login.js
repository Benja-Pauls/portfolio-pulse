export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { pin } = req.body;
  const correctPin = process.env.PORTFOLIO_PIN;

  if (!correctPin) {
    return res.status(500).json({ error: 'PIN not configured' });
  }

  if (pin === correctPin) {
    // Set httpOnly cookie — secure, can't be read by JavaScript
    res.setHeader('Set-Cookie', `pp_auth=1; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${60 * 60 * 24 * 30}`);
    return res.status(200).json({ ok: true });
  }

  return res.status(401).json({ error: 'Incorrect PIN' });
}
