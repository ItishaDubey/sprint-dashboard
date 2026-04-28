require('dotenv').config();
const express = require('express');
const cron = require('node-cron');
const { google } = require('googleapis');
const app = express();
const PORT = process.env.PORT || 3000;

// ─── CONFIG ────────────────────────────────────────────────────────────────
const SPREADSHEET_ID = '1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY';
const SPRINT_SHEET = 'SPRINT 69 27 Apr - 8 May';
const RESOURCE_SHEET = 'Resource Sheet';

// Pod definitions — update this when team changes
const PODS = [
  {
    key: 'engage', name: 'KGeN Engage', color: '#185FA5', bg: '#EBF5FB',
    sectionMatch: ['Engage Activities'],
    pm: 'Mandeep', lead: 'Guru',
  },
  {
    key: 'kstore', name: 'KStore', color: '#3B6D11', bg: '#EAF7E6',
    sectionMatch: ['exlr8 <> kstore', 'exlr8'],
    pm: 'Shishir / Russel', lead: 'Julian',
  },
  {
    key: 'hl', name: 'Humyn Labs', color: '#9E3360', bg: '#FDF0F5',
    sectionMatch: ['HL Tasks', 'QA Items & Releases', 'To be Released'],
    pm: 'Saksham', lead: 'Yogesh',
    subsections: ['HL Tasks', 'QA Items & Releases'],
  },
  {
    key: 'devsec', name: 'DevSec', color: '#854F0B', bg: '#FFFBF0',
    sectionMatch: ['Devops and Security', 'Devops'],
    pm: 'Itisha (TPM)', lead: 'Itisha',
  },
];

// ─── GOOGLE DRIVE / SHEETS AUTH ────────────────────────────────────────────
function getAuthClient() {
  // Supports both service account JSON (GOOGLE_SERVICE_ACCOUNT_JSON env var)
  // and OAuth2 access token (GOOGLE_ACCESS_TOKEN env var)
  if (process.env.GOOGLE_SERVICE_ACCOUNT_JSON) {
    const creds = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON);
    return new google.auth.GoogleAuth({
      credentials: creds,
      scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly'],
    });
  }
  // Fallback: use API key for public sheets
  return null;
}

async function readSheet(sheetName) {
  try {
    const auth = getAuthClient();
    const sheets = google.sheets({ version: 'v4', auth });
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId: SPREADSHEET_ID,
      range: `'${sheetName}'!A:AE`,
    });
    return res.data.values || [];
  } catch (e) {
    console.error(`Failed to read sheet "${sheetName}":`, e.message);
    return [];
  }
}

// ─── PARSE SPRINT SHEET ────────────────────────────────────────────────────
function parseSprintData(rows) {
  if (!rows || rows.length < 2) return [];
  const items = [];
  let currentSection = 'Unknown';

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r) continue;

    const col0 = (r[0] || '').trim();
    const col1 = (r[1] || '').trim();

    // Section header rows: col0 has a label, col1 is empty
    if (col0 && !col1) {
      currentSection = col0;
      continue;
    }

    // Skip empty rows
    if (!col1) continue;

    const space = (r[23] || '').trim();
    const assignee = (r[27] || '').trim();
    const status = (r[28] || '').trim();
    const jira = (r[29] || '').trim();
    const notes = (r[12] || '').trim();

    // Skip rows that are just section data with no feature
    if (!col1 || col1.length < 3) continue;

    items.push({
      feature: col1.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim(),
      owner: col0,
      space,
      assignee,
      status: status || 'To Do',
      jira,
      notes,
      section: currentSection,
    });
  }
  return items;
}

// ─── PARSE RESOURCE SHEET ──────────────────────────────────────────────────
function parseResources(rows) {
  // Resource sheet has Name, Role, Pod, Status columns
  // Adapt this to match your actual Resource Sheet structure
  const resources = {};
  if (!rows || rows.length < 2) return resources;

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r || !r[0]) continue;
    const name = (r[0] || '').trim();
    const pod = (r[2] || r[1] || '').trim();
    const status = (r[3] || 'Active').trim();
    if (name && pod && status !== 'Resigned') {
      if (!resources[pod]) resources[pod] = [];
      resources[pod].push(name);
    }
  }
  return resources;
}

// ─── HTML GENERATOR ────────────────────────────────────────────────────────
function statusPill(s) {
  const m = {
    'Done': ['#e8f5e9','#1b5e20'],
    'In QA': ['#e8f5e9','#2e7d32'],
    'In Progress': ['#e3f2fd','#0d47a1'],
    'Dev in Progress': ['#e3f2fd','#0d47a1'],
    'Review In Progress': ['#fff8e1','#e65100'],
    'Blocked': ['#ffebee','#b71c1c'],
    'Bug': ['#ffebee','#c62828'],
  };
  const [bg, color] = m[s] || ['#f5f4f0','#888'];
  return `<span style="font-size:10px;padding:1px 7px;border-radius:10px;font-weight:500;background:${bg};color:${color}">${s}</span>`;
}

function dotColor(s) {
  if (s === 'Done' || s === 'In QA') return '#2e7d32';
  if (s && s.includes('Progress')) return '#1565c0';
  if (s && s.includes('Review')) return '#e65100';
  if (s === 'Blocked' || s === 'Bug') return '#c62828';
  return '#d0cdc7';
}

function renderItems(items) {
  return items.map(item => {
    const blocker = item.notes && item.notes.includes('BLOCKED')
      ? `<div style="font-size:10px;color:#c62828;background:#ffebee;border-radius:4px;padding:2px 6px;margin-top:3px;display:inline-block">${item.notes.replace('BLOCKED: ','').replace('BLOCKED:','')}</div>`
      : '';
    const jira = item.jira && item.jira !== '-' && item.jira.length > 2
      ? `<span style="font-size:10px;font-family:monospace;color:#bbb">${item.jira}</span>` : '';
    const assignee = item.assignee && item.assignee !== '-' && item.assignee.length > 1
      ? `<span style="font-size:10px;color:#bbb">${item.assignee}</span>` : '';
    return `<div style="padding:7px 16px;display:flex;align-items:flex-start;gap:8px;border-bottom:1px solid #faf9f7">
      <span style="width:6px;height:6px;border-radius:50%;background:${dotColor(item.status)};margin-top:5px;flex-shrink:0;display:inline-block"></span>
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;color:#111;line-height:1.4">${item.feature}</div>
        <div style="margin-top:3px;display:flex;gap:6px;align-items:center;flex-wrap:wrap">${jira}${statusPill(item.status)}${assignee}</div>
        ${blocker}
      </div>
    </div>`;
  }).join('');
}

function renderPod(pod, items, resources) {
  const podItems = items.filter(i =>
    pod.sectionMatch.some(s => i.section.toLowerCase().includes(s.toLowerCase()))
  );

  // Build team tags from resource sheet or fall back to assignees
  const podPeople = resources[pod.key] || resources[pod.name] || [];
  const teamHtml = podPeople.length > 0
    ? podPeople.map(p => `<span style="font-size:10px;background:#f5f4f0;color:#666;padding:2px 7px;border-radius:10px">${p}</span>`).join('')
    : '';

  let itemsHtml = '';
  if (pod.subsections) {
    pod.subsections.forEach(sub => {
      const subItems = podItems.filter(i => i.section.toLowerCase().includes(sub.toLowerCase()));
      if (!subItems.length) return;
      itemsHtml += `<div style="padding:5px 16px 2px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:#bbb;border-top:1px solid #f5f4f0;margin-top:2px">${sub}</div>`;
      itemsHtml += renderItems(subItems);
    });
    const matched = new Set(pod.subsections.flatMap(s => podItems.filter(i => i.section.toLowerCase().includes(s.toLowerCase()))));
    const rest = podItems.filter(i => !matched.has(i));
    if (rest.length) itemsHtml += renderItems(rest);
  } else {
    itemsHtml = renderItems(podItems);
  }

  const counts = {
    done: podItems.filter(i => i.status === 'Done' || i.status === 'In QA').length,
    prog: podItems.filter(i => i.status && i.status.includes('Progress')).length,
    blocked: podItems.filter(i => i.status === 'Blocked').length,
  };

  return `<div style="background:#fff;border-radius:10px;border:1px solid #e8e6e0;overflow:hidden;margin-bottom:0">
    <div style="padding:12px 16px 10px;border-bottom:1px solid #f0ede8;background:${pod.bg}">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <span style="display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:#111">
          <span style="width:8px;height:8px;border-radius:50%;background:${pod.color};display:inline-block"></span>
          ${pod.name}
        </span>
        <span style="font-size:11px;color:#999">${podItems.length} items &nbsp;·&nbsp; <span style="color:#2e7d32">${counts.done} done</span>${counts.blocked ? ` &nbsp;·&nbsp; <span style="color:#c62828">${counts.blocked} blocked</span>` : ''}</span>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:4px">
        <span style="font-size:10px;background:#111;color:#fff;padding:2px 7px;border-radius:10px">PM: ${pod.pm}</span>
        <span style="font-size:10px;background:#444;color:#fff;padding:2px 7px;border-radius:10px">TL: ${pod.lead}</span>
        ${teamHtml}
      </div>
    </div>
    <div>${itemsHtml || '<div style="padding:14px 16px;font-size:12px;color:#bbb">No items in this sprint</div>'}</div>
  </div>`;
}

function buildHTML(items, resources, sprintName, lastUpdated) {
  const total = items.length;
  const done = items.filter(i => i.status === 'Done' || i.status === 'In QA').length;
  const prog = items.filter(i => i.status && (i.status.includes('Progress') || i.status.includes('Review'))).length;
  const blocked = items.filter(i => i.status === 'Blocked').length;
  const notStarted = total - done - prog - blocked;

  const podsHtml = PODS.map(p => renderPod(p, items, resources)).join('');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${sprintName} — Founder Update</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f4f0;color:#1a1a1a;min-height:100vh}
.hdr{background:#fff;border-bottom:1px solid #e8e6e0;padding:18px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:10}
.stats{background:#fff;border-bottom:1px solid #e8e6e0;padding:12px 32px;display:flex;gap:20px;flex-wrap:wrap;overflow-x:auto}
.stat{display:flex;flex-direction:column;min-width:60px}
.stat-n{font-size:22px;font-weight:600;color:#111;line-height:1}
.stat-l{font-size:10px;color:#999;margin-top:3px;text-transform:uppercase;letter-spacing:.04em}
.main{padding:20px 32px;max-width:1100px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.slabel{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#999;margin:20px 0 10px}
.team-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:4px}
.divider{width:1px;background:#e8e6e0;margin:0 4px}
.pill-done{color:#1b5e20;font-weight:600}
.pill-block{color:#c62828;font-weight:600}
@media(max-width:680px){.grid{grid-template-columns:1fr}.main{padding:16px}.stats{padding:10px 16px}.hdr{padding:14px 16px}}
</style>
</head>
<body>
<div class="hdr">
  <div>
    <div style="font-size:18px;font-weight:600;color:#111">${sprintName}</div>
    <div style="font-size:12px;color:#888;margin-top:2px">Founder update &middot; auto-refreshed daily from Google Drive &middot; ${lastUpdated}</div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <span style="font-size:11px;padding:4px 10px;border-radius:12px;background:#f5f4f0;color:#666">${total} items</span>
    <span style="font-size:11px;padding:4px 10px;border-radius:12px;background:#e8f5e9;color:#1b5e20;font-weight:500">${done} Done / QA</span>
    <span style="font-size:11px;padding:4px 10px;border-radius:12px;background:#e3f2fd;color:#0d47a1;font-weight:500">${prog} In Progress</span>
    <span style="font-size:11px;padding:4px 10px;border-radius:12px;background:#ffebee;color:#c62828;font-weight:500">${blocked} Blocked</span>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="stat-n">${total}</div><div class="stat-l">Total items</div></div>
  <div class="divider"></div>
  <div class="stat"><div class="stat-n" style="color:#1b5e20">${done}</div><div class="stat-l">Done / QA</div></div>
  <div class="divider"></div>
  <div class="stat"><div class="stat-n" style="color:#0d47a1">${prog}</div><div class="stat-l">In Progress</div></div>
  <div class="divider"></div>
  <div class="stat"><div class="stat-n" style="color:#c62828">${blocked}</div><div class="stat-l">Blocked</div></div>
  <div class="divider"></div>
  <div class="stat"><div class="stat-n">${notStarted}</div><div class="stat-l">Not started</div></div>
  <div class="divider"></div>
  <div class="stat"><div class="stat-n">4</div><div class="stat-l">Pods</div></div>
  <div class="divider"></div>
  <div class="stat"><div class="stat-n">29</div><div class="stat-l">Engineers</div></div>
</div>

<div class="main">
  <div class="slabel">Pods & work items</div>
  <div class="grid">${podsHtml}</div>

  <div class="slabel" style="margin-top:24px">Team updates</div>
  <div class="team-grid">
    <div style="background:#fff;border-radius:8px;border:1px solid #ffcdd2;padding:10px 14px">
      <div style="font-size:10px;font-weight:600;color:#c62828;margin-bottom:4px;text-transform:uppercase">Resigned</div>
      <div style="font-size:13px;font-weight:500">Avish</div>
      <div style="font-size:11px;color:#888;margin-top:2px">WFH 9–17 Apr (father's accident). Tasks re-routed.</div>
    </div>
    <div style="background:#fff;border-radius:8px;border:1px solid #ffe0b2;padding:10px 14px">
      <div style="font-size:10px;font-weight:600;color:#e65100;margin-bottom:4px;text-transform:uppercase">Replacement in progress</div>
      <div style="font-size:13px;font-weight:500">Akshay (HL Backend)</div>
      <div style="font-size:11px;color:#888;margin-top:2px">3-month notice period. Hiring underway.</div>
    </div>
    <div style="background:#fff;border-radius:8px;border:1px solid #ffe0b2;padding:10px 14px">
      <div style="font-size:10px;font-weight:600;color:#e65100;margin-bottom:4px;text-transform:uppercase">Replacement in progress</div>
      <div style="font-size:13px;font-weight:500">Shivam (GKMIT)</div>
      <div style="font-size:11px;color:#888;margin-top:2px">3-month notice period. Hiring underway.</div>
    </div>
    <div style="background:#fff;border-radius:8px;border:1px solid #e8e6e0;padding:10px 14px">
      <div style="font-size:10px;font-weight:600;color:#888;margin-bottom:4px;text-transform:uppercase">No replacement needed</div>
      <div style="font-size:13px;font-weight:500">Raghav & Pankaj (GKMIT)</div>
      <div style="font-size:11px;color:#888;margin-top:2px">Update to be sent to GKMIT.</div>
    </div>
  </div>

  <div style="text-align:center;padding:32px 0 16px;font-size:11px;color:#ccc">
    Auto-generated &middot; Source: Google Drive Tech Resource Planning &middot; ${lastUpdated}
  </div>
</div>
</body>
</html>`;
}

// ─── STATE ─────────────────────────────────────────────────────────────────
let cachedHTML = '<html><body style="font-family:sans-serif;padding:40px"><h2>Loading sprint data…</h2><p>First refresh takes ~10 seconds.</p></body></html>';
let lastUpdated = 'Never';

async function refresh() {
  console.log('[refresh] Reading sheets…');
  try {
    const [sprintRows, resourceRows] = await Promise.all([
      readSheet(SPRINT_SHEET),
      readSheet(RESOURCE_SHEET),
    ]);

    const items = parseSprintData(sprintRows);
    const resources = parseResources(resourceRows);
    lastUpdated = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) + ' IST';

    cachedHTML = buildHTML(items, resources, 'Sprint 69 — 27 Apr–8 May 2026', lastUpdated);
    console.log(`[refresh] Done — ${items.length} items, updated at ${lastUpdated}`);
  } catch (e) {
    console.error('[refresh] Error:', e.message);
  }
}

// ─── ROUTES ────────────────────────────────────────────────────────────────
app.get('/', (req, res) => {
  res.setHeader('Content-Type', 'text/html');
  res.send(cachedHTML);
});

app.get('/health', (req, res) => res.json({ ok: true, lastUpdated }));

app.get('/refresh', async (req, res) => {
  // Manual trigger: GET /refresh?secret=YOUR_SECRET
  if (process.env.REFRESH_SECRET && req.query.secret !== process.env.REFRESH_SECRET) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  await refresh();
  res.json({ ok: true, lastUpdated });
});

// ─── CRON: refresh every day at 8:30am IST ─────────────────────────────────
cron.schedule('0 3 * * *', refresh, { timezone: 'UTC' }); // 3am UTC = 8:30am IST

// ─── START ─────────────────────────────────────────────────────────────────
app.listen(PORT, async () => {
  console.log(`Server running on port ${PORT}`);
  await refresh(); // Load on startup
});
