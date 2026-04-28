import json, os, re
from datetime import datetime, timezone

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY")

# Section headers in the sheet → pod config
POD_SECTIONS = {
    "Engage Activities":   {"id":"engage",   "name":"KGeN Engage",              "color":"#185FA5","headBg":"#EBF5FB","lead":"Guru",    "note":""},
    "HL Tasks":            {"id":"hl_audio","name":"Humyn Labs — Audio",         "color":"#9E3360","headBg":"#FDF0F5","lead":"Yogesh",  "note":"Multi-pipeline: validation, annotation, collection, account infra & data ops"},
    "QA Items & Releases": {"id":"hl_ego",  "name":"Humyn Labs — Egocentric",    "color":"#9E3360","headBg":"#FDF0F5","lead":"Karthik", "note":""},
    "exlr8 <> kstore":    {"id":"kstore",   "name":"KStore",                     "color":"#3B6D11","headBg":"#EAF7E6","lead":"Julian",  "note":""},
    "Devops and Security": {"id":"devsec",  "name":"DevSec",                     "color":"#854F0B","headBg":"#FFFBF0","lead":"Itisha",  "note":""},
}

# Pod display order — HL first
POD_ORDER = ["hl_audio","hl_ego","engage","kstore","devsec"]

STATIC_TEAMS = {
    "engage":   ["Harshada","Manpreet","Namrata","Shaurya","Swetha (QA)"],
    "kstore":   ["Jitendra","Shahid","Relin (QA)"],
    "hl_audio": ["Guru","Shaurya","Pratik","Namrata","Nilesh","Jaya","Sameer","Kevin (QA)","Swetha (QA)"],
    "hl_ego":   ["Karthik","Avinash"],
    "devsec":   ["Arun Kumar Krishna (DevOps)","Karan Sabharwal (Security)"],
}

TEAM_UPDATES = [
    {"type":"resigned",    "name":"Avish",               "detail":"Father's accident. WFH 9-17 Apr. Tasks re-routed.", "status":"WFH 9-17 Apr"},
    {"type":"replacement", "name":"Akshay (HL Backend)",  "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"replacement", "name":"Shivam (GKMIT)",       "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"info",        "name":"Raghav & Pankaj (GKMIT)","detail":"No replacement needed. Update to GKMIT pending.", "status":"Update to GKMIT"},
]

SECTION_LABELS = list(POD_SECTIONS.keys())

# Known section header keywords — rows with these in col0 and empty col1 are headers not items
SECTION_KEYWORDS = [
    "engage activities","hl tasks","qa items","releases","devops","security",
    "exlr8","kstore","to be released","standalone"
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
        raise RuntimeError("No sprint tab found in: " + str(titles))
    sprint_tabs.sort(reverse=True)
    print("Using:", sprint_tabs[0][1])
    return sprint_tabs[0][1]

def read_tab(service, tab):
    r = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'").execute()
    return r.get("values",[])

def safe(row, i):
    try:
        v = row[i]
        return str(v).strip() if v else ""
    except:
        return ""

def is_section_header(owner, feature):
    """True if this row is a section label, not a real work item."""
    if feature:
        return False
    ol = owner.lower()
    return any(kw in ol for kw in SECTION_KEYWORDS)

def is_real_item(owner, feature):
    """True only if there's an actual feature/task name."""
    if not feature:
        return False
    # skip column header row
    if feature in ("Features", "Module Owner"):
        return False
    # skip known noise
    if feature in ("Shield Disable???",):
        return False
    # skip rows where feature looks like a section label
    fl = feature.lower()
    if any(kw in fl for kw in SECTION_KEYWORDS):
        return False
    return True

def parse(rows):
    items = []
    section = "Engage Activities"

    for row in rows[1:]:
        owner   = safe(row, 0)
        feature = safe(row, 1)
        notes   = safe(row, 12)
        assignee= safe(row, 27)
        status  = safe(row, 28)
        jira    = safe(row, 29)

        # detect section header
        if is_section_header(owner, feature):
            for label in SECTION_LABELS:
                if label.lower() in owner.lower():
                    section = label
                    break
            continue

        if not is_real_item(owner, feature):
            continue

        # only include rows that have a Jira key OR a status — these are real sprint tasks
        # rows with neither are likely backlog/future items slipping in
        has_jira   = bool(jira and jira not in ("-","FALSE","False"))
        has_status = bool(status and status not in ("-","FALSE","False"))
        has_sprint = False
        try:
            sprint_col = safe(row, 26)  # Sprint column
            has_sprint = bool(sprint_col and sprint_col.strip())
        except:
            pass

        if not (has_jira or has_status or has_sprint):
            continue

        is_blocked = any(x in notes for x in ["BLOCKED","TSD is pending","waiting from product","waiting for clarity"])
        display_status = "Blocked" if is_blocked and status in ("To Do","","To Do ") else (status or "To Do")

        items.append({
            "section":  section,
            "feature":  feature.replace("\n"," ").strip(),
            "jira":     jira if has_jira else "-",
            "status":   display_status,
            "assignee": assignee or "-",
            "notes":    notes.replace("\n"," ").strip() if is_blocked else "",
        })

    return items

def build_pods(items):
    sec2pod = {s: c["id"] for s, c in POD_SECTIONS.items()}
    pod_items = {pid: [] for pid in POD_ORDER}
    for i in items:
        pid = sec2pod.get(i["section"])
        if pid and pid in pod_items:
            pod_items[pid].append(i)
    pods = []
    for pid in POD_ORDER:
        cfg = next(c for c in POD_SECTIONS.values() if c["id"] == pid)
        pods.append({
            **cfg,
            "team":  STATIC_TEAMS.get(pid, []),
            "items": pod_items[pid],
        })
    return pods

def calc_stats(items):
    total   = len(items)
    done    = sum(1 for i in items if i["status"].lower() in ("done","in qa") or "done" in i["status"].lower())
    prog    = sum(1 for i in items if "progress" in i["status"].lower() or "review" in i["status"].lower())
    blocked = sum(1 for i in items if "block" in i["status"].lower())
    return {"total":total,"done":done,"inProgress":prog,"blocked":blocked,"notStarted":total-done-prog-blocked}

def main():
    svc  = get_service()
    tab  = find_latest_tab(svc)
    rows = read_tab(svc, tab)
    items = parse(rows)
    pods  = build_pods(items)

    print(f"Total items parsed: {len(items)}")
    for p in pods:
        print(f"  {p['name']}: {len(p['items'])} items")

    m = re.search(r"(\d+)\s+(.+)", tab, re.IGNORECASE)
    data = {
        "generatedAt":  datetime.now(timezone.utc).isoformat(),
        "sprintNumber": m.group(1) if m else "?",
        "sprintDates":  m.group(2).strip() if m else tab,
        "sheetName":    tab,
        "stats":        calc_stats(items),
        "pods":         pods,
        "teamUpdates":  TEAM_UPDATES,
    }

    with open("data.json","w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # stamp into index.html
    data_str = json.dumps(data, ensure_ascii=True)
    html = open("index.html").read()
    # reset any previous injection first
    html = re.sub(r'var D = .*?; /\* DATA_PLACEHOLDER \*/', 'var D = null; /* DATA_PLACEHOLDER */', html)
    html = html.replace("var D = null; /* DATA_PLACEHOLDER */", f"var D = {data_str};")
    open("index.html","w").write(html)
    print("Done.")

if __name__ == "__main__":
    main()
