const https = require('https');

const OWNER    = 'ItishaDubey';
const REPO     = 'sprint-dashboard';
const BRANCH   = 'main';
const FILE     = 'team_config.json';
const WORKFLOW = 'refresh.yml';

function ghRequest(path, method, body, token) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : null;
    const req = https.request({
      hostname: 'api.github.com',
      path,
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'sprint-dashboard-admin',
        ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } : {})
      }
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN not set in Vercel env vars' });

  const config = req.body;
  if (!config || typeof config !== 'object' || !Array.isArray(config.teamUpdates)) {
    return res.status(400).json({ error: 'Invalid body' });
  }

  try {
    // Get current SHA of team_config.json
    const current = await ghRequest(`/repos/${OWNER}/${REPO}/contents/${FILE}?ref=${BRANCH}`, 'GET', null, token);
    if (current.status !== 200) throw new Error(`GitHub GET failed: ${current.status}`);
    const sha = current.body.sha;

    // Commit updated file
    const content = Buffer.from(JSON.stringify(config, null, 2)).toString('base64');
    const put = await ghRequest(`/repos/${OWNER}/${REPO}/contents/${FILE}`, 'PUT', {
      message: 'chore: update team config via admin panel',
      content,
      sha,
      branch: BRANCH
    }, token);
    if (put.status !== 200 && put.status !== 201) throw new Error(`GitHub PUT failed: ${put.status}`);

    // Trigger the daily refresh workflow so HTML re-embeds the new config
    await ghRequest(`/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, 'POST', { ref: BRANCH }, token);

    res.json({ ok: true, message: 'Saved — dashboard will refresh in ~30 seconds' });
  } catch (err) {
    console.error('save.js error:', err.message);
    res.status(500).json({ error: err.message });
  }
};
