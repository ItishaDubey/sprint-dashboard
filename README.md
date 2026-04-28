# Sprint Dashboard

Founder-friendly sprint tracker. Reads directly from your Google Sheet daily.
Auto-deployed to Vercel. Zero manual updates needed.

## How it works

1. GitHub Action runs every day at 9:00 AM IST
2. `fetch_data.py` reads your Google Sheet and writes `data.json`
3. The commit triggers a Vercel redeploy
4. `index.html` reads `data.json` and renders the dashboard

**Shareable URL:** `https://your-project.vercel.app`

---

## One-time setup (≈15 minutes)

### Step 1: Create a Google Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable the **Google Sheets API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Give it any name (e.g. `sprint-dashboard`)
6. Click **Create and continue**, skip role, click **Done**
7. Click the service account → **Keys → Add Key → Create new key → JSON**
8. Download the JSON file — keep it safe, you'll paste its contents as a secret

### Step 2: Share the Google Sheet with the service account

1. Open your Tech Resource Planning Google Sheet
2. Click **Share**
3. Add the service account email (looks like `sprint-dashboard@your-project.iam.gserviceaccount.com`)
4. Give it **Viewer** access
5. Click **Send**

### Step 3: Push this folder to a new GitHub repo

```bash
cd sprint-dashboard
git init
git add .
git commit -m "init sprint dashboard"
gh repo create sprint-dashboard --public --push --source=.
```

### Step 4: Add GitHub Secrets

Go to your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these three secrets:

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of the JSON key file you downloaded |
| `SPREADSHEET_ID` | `1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY` |
| `SPRINT_SHEET_NAME` | `SPRINT 69 27 Apr - 8 May` |

### Step 5: Connect to Vercel

1. Go to [vercel.com/new](https://vercel.com/new)
2. Import your GitHub repo `sprint-dashboard`
3. Framework: **Other** (static site)
4. Root directory: `/` (default)
5. Output directory: leave blank
6. Click **Deploy**

Your URL is ready: `https://sprint-dashboard-xxx.vercel.app`

---

## Day-to-day usage

### Updating sprint status / work items
Just edit the Google Sheet. The dashboard updates automatically at 9 AM IST.

### Someone joins or leaves the team
Edit the **Resource Sheet** tab in the Google Sheet.
The team roster on each pod card updates overnight.

### New sprint starts
1. There will be a new sheet tab (e.g. `SPRINT 70 12 May - 23 May`)
2. Go to GitHub repo → **Settings → Secrets → `SPRINT_SHEET_NAME`**
3. Update the value to the new tab name
4. The action will pick it up at the next 9 AM run
5. Or trigger it manually: GitHub → Actions → "Daily sprint data refresh" → **Run workflow**

### Run immediately (force refresh)
GitHub → Actions → "Daily sprint data refresh" → **Run workflow** → Run

---

## File structure

```
sprint-dashboard/
├── index.html          ← the dashboard (reads data.json)
├── data.json           ← auto-generated daily, DO NOT edit manually
├── fetch_data.py       ← reads Google Sheet, writes data.json
└── .github/
    └── workflows/
        └── refresh.yml ← GitHub Actions cron job
```
