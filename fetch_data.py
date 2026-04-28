import json, os, sys, re
from datetime import datetime, timezone

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY")

POD_SECTIONS = {
    "Engage Activities":   {"id":"engage",   "name":"KGeN Engage",            "color":"#185FA5","headBg":"#EBF5FB","pm":"Mandeep",        "lead":"Guru"},
    "exlr8 <> kstore":    {"id":"kstore",   "name":"KStore",                  "color":"#3B6D11","headBg":"#EAF7E6","pm":"Shishir / Russel","lead":"Julian"},
    "HL Tasks":            {"id":"hl_audio","name":"Humyn Labs - Audio",       "color":"#9E3360","headBg":"#FDF0F5","pm":"Saksham",        "lead":"Yogesh"},
    "QA Items & Releases": {"id":"hl_ego",  "name":"Humyn Labs - Egocentric",  "color":"#9E3360","headBg":"#FDF0F5","pm":"Adnaan",         "lead":"Karthik / Avinash"},
    "Devops and Security": {"id":"devsec",  "name":"DevSec",                   "color":"#854F0B","headBg":"#FFFBF0","pm":"Itisha (TPM)",   "lead":"Itisha"},
}

STATIC_TEAMS = {
    "engage":   ["Harshada","Manpreet","Namrata","Akshay","Shaurya","Swetha (QA)"],
    "kstore":   ["Julian","Karthik","Jitendra","Raghav","Aditya","Shahid","Pankaj","Relin (QA)","Yuvaraj (QA)"],
    "hl_audio": ["Namrata","Nilesh","Jaya","Avish","Avinash","Kumaragurubaran","Shaurya (FE)","Sameer (FE)","Shivam (FE)","Kevin (QA)","Swetha (QA)"],
    "hl_ego":   ["Karthik","Avinash"],
    "devsec":   ["Arun Kumar Krishna (DevOps)","Karan Sabharwal (Security)"],
}

TEAM_UPDATES = [
    {"type":"resigned",    "name":"Avish",               "detail":"Father's accident. WFH 9-17 Apr. Tasks re-routed.", "status":"WFH 9-17 Apr"},
    {"type":"replacement", "name":"Akshay (HL Backend)",  "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"replacement", "name":"Shivam (GKMIT)",       "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"info",        "name":"Raghav & Pankaj (GKMIT)","detail":"No replacement needed. Update to GKMIT pending.", "status":"Update to GKMIT"},
]

def get_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return build("sheets","v4",credentials=creds,cache_discovery=False)

def find_latest_tab(service):
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, fields="sheets.properties.title").execute()
    titles = [s["properties"]["title"] for s in meta.get("sheets",[])]
    print("Tabs:", titles)
    sprint_tabs = []
    for t in titles:
        m = re.search(r"SPRINT\s+(\d+)", t, re.IGNORECASE)
        if m:
            sprint_tabs.append((int(m.group(1)), t))
    if not sprint_tabs:
        raise RuntimeError("No sprint tab found")
    sprint_tabs.sort(reverse=True)
    print("Using:", sprint_tabs[0][1])
    return sprint_tabs[0][1]

def read_tab(service, tab):
    r = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'").execute()
    return r.get("values",[])

def safe(row, i):
    try: return str(row[i]).strip() if row[i] else ""
    except: return ""

def parse(rows):
    items = []
    section = "Engage Activities"
    for row in rows[1:]:
        owner=safe(row,0); feature=safe(row,1); notes=safe(row,12)
        assignee=safe(row,27); status=safe(row,28); jira=safe(row,29)
        if owner and not feature:
            for k in POD_SECTIONS:
                if k.lower() in owner.lower(): section=k; break
            continue
        if not feature or feature in ("Features","Shield Disable???") or owner=="Module Owner": continue
        is_blocked = any(x in notes for x in ["BLOCKED","TSD is pending","waiting from product"])
        items.append({
            "section": section,
            "feature": feature.replace("\n"," ").strip(),
            "jira": jira or "-",
            "status": "Blocked" if is_blocked and status in ("To Do","") else (status or "To Do"),
            "assignee": assignee or "-",
            "notes": notes.replace("\n"," ").strip() if is_blocked else "",
        })
    return items

def build_pods(items):
    order = ["engage","kstore","hl_audio","hl_ego","devsec"]
    sec2pod = {s:c["id"] for s,c in POD_SECTIONS.items()}
    pod_items = {p:[] for p in order}
    for i in items:
        pid = sec2pod.get(i["section"])
        if pid: pod_items[pid].append(i)
    pods = []
    for pid in order:
        cfg = next(c for c in POD_SECTIONS.values() if c["id"]==pid)
        pods.append({**cfg, "team": STATIC_TEAMS.get(pid,[]), "items": pod_items[pid]})
    return pods

def calc_stats(items):
    total=len(items)
    done=sum(1 for i in items if "done" in i["status"].lower() or i["status"]=="In QA")
    prog=sum(1 for i in items if "progress" in i["status"].lower() or "review" in i["status"].lower())
    blocked=sum(1 for i in items if "block" in i["status"].lower())
    return {"total":total,"done":done,"inProgress":prog,"blocked":blocked,"notStarted":total-done-prog-blocked}

def main():
    svc = get_service()
    tab = find_latest_tab(svc)
    rows = read_tab(svc, tab)
    items = parse(rows)
    pods = build_pods(items)
    m = re.search(r"(\d+)\s+(.+)", tab, re.IGNORECASE)
    data = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sprintNumber": m.group(1) if m else "?",
        "sprintDates": m.group(2).strip() if m else tab,
        "sheetName": tab,
        "stats": calc_stats(items),
        "pods": pods,
        "teamUpdates": TEAM_UPDATES,
    }

    # write data.json
    with open("data.json","w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # inject into index.html — replace the placeholder
    data_str = json.dumps(data, ensure_ascii=True)
    html = open("index.html").read()
    html = html.replace("var D = null; /* DATA_PLACEHOLDER */", f"var D = {data_str};")
    open("index.html","w").write(html)

    print(f"Done: sprint {data['sprintNumber']}, {len(items)} items")

if __name__ == "__main__":
    main()
