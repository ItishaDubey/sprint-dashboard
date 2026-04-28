"""
fetch_data.py
Reads the Tech Resource Planning Google Sheet and writes data.json
for the sprint dashboard. Runs daily via GitHub Actions.

Requirements:
  pip install google-auth google-auth-httplib2 google-api-python-client openpyxl requests

Env vars needed (set as GitHub Secrets):
  GOOGLE_SERVICE_ACCOUNT_JSON  — contents of your service account key JSON
  SPREADSHEET_ID               — the Google Sheets file ID
  SPRINT_SHEET_NAME            — e.g. "SPRINT 69 27 Apr - 8 May"
"""

import json
import os
import sys
import re
from datetime import datetime, timezone

# ── config ─────────────────────────────────────────────────────────────────
SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY")
SPRINT_SHEET     = os.environ.get("SPRINT_SHEET_NAME", "SPRINT 69 27 Apr - 8 May")
RESOURCE_SHEET   = os.environ.get("RESOURCE_SHEET_NAME", "Resource Sheet")
OUTPUT_FILE      = "data.json"

# Pod definitions — maps section headers in the sheet to pod config
POD_CONFIG = {
    "Engage Activities": {
        "id": "engage",
        "name": "KGeN Engage",
        "color": "#185FA5",
        "headBg": "#EBF5FB",
        "pm": "Mandeep",
        "lead": "Guru (Kumaragurubaran)",
    },
    "exlr8 <> kstore": {
        "id": "kstore",
        "name": "KStore",
        "color": "#3B6D11",
        "headBg": "#EAF7E6",
        "pm": "Shishir / Russel",
        "lead": "Julian",
    },
    "HL Tasks": {
        "id": "hl_audio",
        "name": "Humyn Labs — Audio",
        "color": "#9E3360",
        "headBg": "#FDF0F5",
        "pm": "Saksham",
        "lead": "Yogesh",
    },
    "QA Items & Releases": {
        "id": "hl_ego",
        "name": "Humyn Labs — Egocentric",
        "color": "#9E3360",
        "headBg": "#FDF0F5",
        "pm": "Adnaan",
        "lead": "Karthik / Avinash",
    },
    "Devops and Security": {
        "id": "devsec",
        "name": "DevSec",
        "color": "#854F0B",
        "headBg": "#FFFBF0",
        "pm": "Itisha (TPM)",
        "lead": "Itisha",
    },
}

# Static team roster per pod — overridden by Resource Sheet if available
STATIC_TEAMS = {
    "engage":   ["Harshada", "Manpreet", "Namrata", "Akshay", "Shaurya", "Swetha (QA)"],
    "kstore":   ["Julian", "Karthik", "Jitendra", "Raghav", "Aditya", "Shahid", "Pankaj", "Relin (QA)", "Yuvaraj (QA)"],
    "hl_audio": ["Namrata", "Nilesh", "Jaya", "Avish", "Avinash", "Kumaragurubaran", "Shaurya (FE)", "Sameer (FE)", "Pratik (FE)", "Shivam (FE)", "Kevin (QA)", "Swetha (QA)"],
    "hl_ego":   ["Karthik", "Avinash"],
    "devsec":   ["Arun Kumar Krishna (DevOps)", "Karan Sabharwal (Security)"],
}

TEAM_UPDATES = [
    {"type": "resigned",    "name": "Avish",             "detail": "Father's accident. WFH 9–17 Apr. Tasks re-routed.", "status": "WFH 9-17 Apr"},
    {"type": "replacement", "name": "Akshay (HL Backend)","detail": "3-month notice period. Replacement hiring underway.", "status": "In Progress"},
    {"type": "replacement", "name": "Shivam (GKMIT)",     "detail": "3-month notice period. Replacement hiring underway.", "status": "In Progress"},
    {"type": "info",        "name": "Raghav & Pankaj (GKMIT)", "detail": "No replacement needed. Update to be sent to GKMIT.", "status": "Update to GKMIT"},
]


def get_sheets_service():
    """Return an authenticated Google Sheets service client."""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set")

    sa_info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_sheet(service, sheet_name):
    """Read all values from a named sheet tab."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"'{sheet_name}'")
        .execute()
    )
    return result.get("values", [])


def safe(row, idx, default=""):
    try:
        v = row[idx]
        return str(v).strip() if v else default
    except IndexError:
        return default


SECTION_LABELS = set(POD_CONFIG.keys())

def parse_sprint_sheet(rows):
    """
    Parse the sprint sheet rows into a list of work items.
    Column mapping (0-indexed):
      0  = Module Owner
      1  = Features
      12 = Scrum Notes
      23 = Space (TECH / HL / DEVSEC)
      27 = Assignee
      28 = Status
      29 = Jira Key
    Section headers: rows where col1 is empty and col0 has a section name.
    """
    items = []
    current_section = "Engage Activities"

    for row in rows[1:]:  # skip header
        owner   = safe(row, 0)
        feature = safe(row, 1)
        notes   = safe(row, 12)
        space   = safe(row, 23)
        assignee= safe(row, 27)
        status  = safe(row, 28)
        jira    = safe(row, 29)

        # Detect section headers
        if owner and not feature:
            for label in SECTION_LABELS:
                if label.lower() in owner.lower():
                    current_section = label
                    break
            # Also catch labels that are only in owner col
            if any(kw in owner for kw in ["Engage", "HL Tasks", "QA Items", "Devops", "exlr8", "kstore"]):
                for label in SECTION_LABELS:
                    if any(kw in owner for kw in label.split()):
                        current_section = label
            continue

        if not feature:
            continue

        # Skip placeholder / header rows
        if feature in ("Features", "Shield Disable???") or owner == "Module Owner":
            continue

        items.append({
            "section":  current_section,
            "owner":    owner,
            "feature":  feature.replace("\n", " ").strip(),
            "notes":    notes.replace("\n", " ").strip(),
            "space":    space,
            "assignee": assignee,
            "status":   status or "To Do",
            "jira":     jira,
        })

    return items


def parse_resource_sheet(rows):
    """
    Extract current team members per pod from the Resource Sheet tab.
    Returns a dict: pod_id -> [name, ...]
    This is a best-effort parse — the resource sheet format varies.
    """
    teams = {k: list(v) for k, v in STATIC_TEAMS.items()}  # start from static
    # TODO: parse rows to override — for now return static defaults
    return teams


def build_pods(items, teams):
    """Group items into pod cards."""
    pods = []
    # Maintain order
    pod_order = ["engage", "kstore", "hl_audio", "hl_ego", "devsec"]
    section_to_pod = {sec: cfg["id"] for sec, cfg in POD_CONFIG.items()}

    pod_items = {pid: [] for pid in pod_order}
    for item in items:
        pid = section_to_pod.get(item["section"])
        if pid:
            pod_items[pid].append(item)

    for pid in pod_order:
        # Find matching POD_CONFIG entry
        cfg = next(c for c in POD_CONFIG.values() if c["id"] == pid)
        pods.append({
            **cfg,
            "team":  teams.get(pid, []),
            "items": pod_items[pid],
        })

    return pods


def count_stats(items):
    total   = len(items)
    done    = sum(1 for i in items if "done" in i["status"].lower() or i["status"] == "In QA")
    prog    = sum(1 for i in items if "progress" in i["status"].lower() or "review" in i["status"].lower())
    blocked = sum(1 for i in items if "block" in i["status"].lower())
    todo    = total - done - prog - blocked
    return {"total": total, "done": done, "inProgress": prog, "blocked": blocked, "notStarted": todo}


def main():
    print(f"Fetching sheet: {SPRINT_SHEET}")

    try:
        service = get_sheets_service()
        sprint_rows   = read_sheet(service, SPRINT_SHEET)
        resource_rows = read_sheet(service, RESOURCE_SHEET) if RESOURCE_SHEET else []
    except Exception as e:
        print(f"WARNING: Could not read Google Sheets ({e}). Writing empty data.", file=sys.stderr)
        sprint_rows = []
        resource_rows = []

    items = parse_sprint_sheet(sprint_rows) if sprint_rows else []
    teams = parse_resource_sheet(resource_rows)
    pods  = build_pods(items, teams)
    stats = count_stats(items)

    # Parse sprint name and dates from sheet tab name
    # e.g. "SPRINT 69 27 Apr - 8 May" → number=69, dates="27 Apr – 8 May"
    m = re.search(r"(\d+)\s+(.+)", SPRINT_SHEET, re.IGNORECASE)
    sprint_number = m.group(1) if m else "?"
    sprint_dates  = m.group(2).strip() if m else SPRINT_SHEET

    data = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sprintNumber": sprint_number,
        "sprintDates":  sprint_dates,
        "sheetName":    SPRINT_SHEET,
        "stats":        stats,
        "pods":         pods,
        "teamUpdates":  TEAM_UPDATES,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Written {OUTPUT_FILE}: {len(items)} items across {len(pods)} pods")


if __name__ == "__main__":
    main()
