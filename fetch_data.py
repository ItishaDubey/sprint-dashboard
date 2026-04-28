"""
fetch_data.py — auto-detects the latest sprint tab, no manual secret updates needed.
"""

import json, os, sys, re
from datetime import datetime, timezone

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY")
OUTPUT_FILE    = "data.json"

POD_SECTIONS = {
    "Engage Activities":   {"id":"engage",   "name":"KGeN Engage",           "color":"#185FA5","headBg":"#EBF5FB","pm":"Mandeep",        "lead":"Guru"},
    "exlr8 <> kstore":    {"id":"kstore",   "name":"KStore",                 "color":"#3B6D11","headBg":"#EAF7E6","pm":"Shishir / Russel","lead":"Julian"},
    "HL Tasks":            {"id":"hl_audio","name":"Humyn Labs — Audio",      "color":"#9E3360","headBg":"#FDF0F5","pm":"Saksham",        "lead":"Yogesh"},
    "QA Items & Releases": {"id":"hl_ego",  "name":"Humyn Labs — Egocentric","color":"#9E3360","headBg":"#FDF0F5","pm":"Adnaan",         "lead":"Karthik / Avinash"},
    "Devops and Security": {"id":"devsec",  "name":"DevSec",                 "color":"#854F0B","headBg":"#FFFBF0","pm":"Itisha (TPM)",   "lead":"Itisha"},
}

STATIC_TEAMS = {
    "engage":   ["Harshada","Manpreet","Namrata","Akshay","Shaurya","Swetha (QA)"],
    "kstore":   ["Julian","Karthik","Jitendra","Raghav","Aditya","Shahid","Pankaj","Relin (QA)","Yuvaraj (QA)"],
    "hl_audio": ["Namrata","Nilesh","Jaya","Avish","Avinash","Kumaragurubaran","Shaurya (FE)","Sameer (FE)","Shivam (FE)","Kevin (QA)","Swetha (QA)"],
    "hl_ego":   ["Karthik","Avinash"],
    "devsec":   ["Arun Kumar Krishna (DevOps)","Karan Sabharwal (Security)"],
}

TEAM_UPDATES = [
    {"type":"resigned",    "name":"Avish",              "detail":"Father's accident. WFH 9–17 Apr. Tasks re-routed.", "status":"WFH 9-17 Apr"},
    {"type":"replacement", "name":"Akshay (HL Backend)","detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"replacement", "name":"Shivam (GKMIT)",     "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"info",        "name":"Raghav & Pankaj (GKMIT)","detail":"No replacement needed. Update to GKMIT pending.","status":"Update to GKMIT"},
]


def get_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return build("sheets","v4",credentials=creds,cache_discovery=False)


def find_latest_sprint_tab(service):
    """
    Reads all sheet tab names from the spreadsheet.
    Picks the tab whose name starts with 'SPRINT' and has the highest sprint number.
    Falls back to any tab containing 'SPRINT' if numbering isn't found.
    """
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties.title"
    ).execute()

    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    print(f"All tabs found: {titles}")

    sprint_tabs = []
    for title in titles:
        m = re.search(r"SPRINT\s+(\d+)", title, re.IGNORECASE)
        if m:
            sprint_tabs.append((int(m.group(1)), title))

    if not sprint_tabs:
        # fallback: any tab with "sprint" in the name
        for title in titles:
            if "sprint" in title.lower():
                print(f"Fallback: using tab '{title}'")
                return title
        raise RuntimeError(f"No sprint tab found. Available tabs: {titles}")

    sprint_tabs.sort(key=lambda x: x[0], reverse=True)
    chosen = sprint_tabs[0][1]
    print(f"Latest sprint tab: '{chosen}' (number {sprint_tabs[0][0]})")
    return chosen


def read_tab(service, tab_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab_name}'"
    ).execute()
    return result.get("values", [])


def safe(row, idx):
    try: return str(row[idx]).strip() if row[idx] else ""
    except IndexError: return ""


def parse_items(rows, sheet_name):
    items = []
    current_section = "Engage Activities"
    section_keys = set(POD_SECTIONS.keys())

    for row in rows[1:]:
        owner   = safe(row, 0)
        feature = safe(row, 1)
        notes   = safe(row, 12)
        space   = safe(row, 23)
        assignee= safe(row, 27)
        status  = safe(row, 28)
        jira    = safe(row, 29)

        # section header detection
        if owner and not feature:
            for label in section_keys:
                if label.lower() in owner.lower():
                    current_section = label
                    break
            continue

        if not feature or feature in ("Features","Shield Disable???") or owner == "Module Owner":
            continue

        is_blocker = any(kw in notes for kw in ["BLOCKED","TSD is pending","waiting from product"])
        display_status = "Blocked" if is_blocker and status in ("To Do","") else (status or "To Do")
        blocker_note = notes if is_blocker else ""

        items.append({
            "section":  current_section,
            "feature":  feature.replace("\n"," ").strip(),
            "jira":     jira or "-",
            "status":   display_status,
            "assignee": assignee or "-",
            "notes":    blocker_note.replace("\n"," ").strip(),
        })

    return items


def build_pods(items):
    pod_order = ["engage","kstore","hl_audio","hl_ego","devsec"]
    sec_to_pod = {s: cfg["id"] for s, cfg in POD_SECTIONS.items()}
    pod_items  = {pid: [] for pid in pod_order}

    for item in items:
        pid = sec_to_pod.get(item["section"])
        if pid:
            pod_items[pid].append(item)

    pods = []
    for pid in pod_order:
        cfg = next(c for c in POD_SECTIONS.values() if c["id"] == pid)
        pods.append({**cfg, "team": STATIC_TEAMS.get(pid,[]), "items": pod_items[pid]})
    return pods


def stats(items):
    total   = len(items)
    done    = sum(1 for i in items if "done" in i["status"].lower() or i["status"]=="In QA")
    prog    = sum(1 for i in items if "progress" in i["status"].lower() or "review" in i["status"].lower())
    blocked = sum(1 for i in items if "block" in i["status"].lower())
    return {"total":total,"done":done,"inProgress":prog,"blocked":blocked,"notStarted":total-done-prog-blocked}


def main():
    svc        = get_service()
    tab        = find_latest_sprint_tab(svc)          # ← auto-detects latest sprint
    rows       = read_tab(svc, tab)
    items      = parse_items(rows, tab)
    pods       = build_pods(items)

    m = re.search(r"(\d+)\s+(.+)", tab, re.IGNORECASE)
    sprint_num  = m.group(1) if m else "?"
    sprint_dates = m.group(2).strip() if m else tab

    data = {
        "generatedAt":  datetime.now(timezone.utc).isoformat(),
        "sprintNumber": sprint_num,
        "sprintDates":  sprint_dates,
        "sheetName":    tab,
        "stats":        stats(items),
        "pods":         pods,
        "teamUpdates":  TEAM_UPDATES,
    }

    with open(OUTPUT_FILE,"w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Done: {len(items)} items, sprint {sprint_num}, written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
