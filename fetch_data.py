import json, os, re
from datetime import datetime, timezone

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY")

# Section header keywords → pod id
# Parser scans col0 for these when col1 is empty — fully position-independent
SECTION_MAP = [
    ("engage activities",          "engage"),
    ("hl tasks",                   "hl_audio"),
    ("humyn labs — audio",         "hl_audio"),
    ("humyn labs - audio",         "hl_audio"),
    ("humyn labs — egocentric",    "hl_ego"),
    ("humyn labs - egocentric",    "hl_ego"),
    ("egocentric",                 "hl_ego"),
    ("qa items",                   "qa_releases"),   # separate bottom section
    ("to be released",             "qa_releases"),
    ("to be merged",               "qa_releases"),
    ("devops and security",        "devsec"),
    ("exlr8",                      "kstore"),
    ("kstore",                     "kstore"),
]

POD_ORDER = ["hl_audio","hl_ego","engage","kstore","devsec"]

POD_CONFIG = {
    "hl_audio": {"name":"Humyn Labs — Audio",     "color":"#9E3360","headBg":"#FDF0F5","lead":"Yogesh",  "note":"Multi-pipeline: validation, annotation, collection, account infra & data ops"},
    "hl_ego":   {"name":"Humyn Labs — Egocentric", "color":"#9E3360","headBg":"#FDF0F5","lead":"Karthik", "note":""},
    "engage":   {"name":"KGeN Engage",             "color":"#185FA5","headBg":"#EBF5FB","lead":"Guru",    "note":""},
    "kstore":   {"name":"KStore",                  "color":"#3B6D11","headBg":"#EAF7E6","lead":"Julian",  "note":""},
    "devsec":   {"name":"DevSec",                  "color":"#854F0B","headBg":"#FFFBF0","lead":"Itisha",  "note":""},
}

STATIC_TEAMS = {
    "engage":   ["Harshada","Manpreet","Namrata","Shaurya","Swetha (QA)"],
    "kstore":   ["Jitendra","Shahid","Relin (QA)"],
    "hl_audio": ["Guru","Shaurya","Pratik","Namrata","Nilesh","Jaya","Sameer","Kevin (QA)","Swetha (QA)"],
    "hl_ego":   ["Karthik","Avinash"],
    "devsec":   ["Arun Kumar Krishna (DevOps)","Karan Sabharwal (Security)"],
}

TEAM_UPDATES = [
    {"type":"resigned",    "name":"Avish",                "detail":"Father's accident. WFH 9-17 Apr. Tasks re-routed.", "status":"WFH 9-17 Apr"},
    {"type":"replacement", "name":"Akshay (HL Backend)",   "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"replacement", "name":"Shivam (GKMIT)",        "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"info",        "name":"Raghav & Pankaj (GKMIT)","detail":"No replacement needed. Update to GKMIT pending.",  "status":"Update to GKMIT"},
]

# Features to always skip regardless of section
SKIP_FEATURES = {
    "Shield Disable???", "Features", "Module Owner",
    "Standalone app for audio collection",
    "HL orchestrator", "Cost and optimisation",
}
SKIP_PARTIAL = [
    "avoid copying recorder tool audio files",
    "quest validation to happen via api at validation tool level",
    "enhancements/optimisation to making the duplication",
    "annotation events and attributes to be added",
    "merge the collection and annotation hitl",
]

def get_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return build("sheets","v4",credentials=creds,cache_discovery=False)

def find_latest_tab(service):
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID, fields="sheets.properties.title").execute()
    titles = [s["properties"]["title"] for s in meta.get("sheets",[])]
    print("Tabs:", titles)
    sprint_tabs = [(int(re.search(r"SPRINT\s+(\d+)",t,re.I).group(1)),t)
                   for t in titles if re.search(r"SPRINT\s+(\d+)",t,re.I)]
    if not sprint_tabs:
        raise RuntimeError("No sprint tab found in: " + str(titles))
    sprint_tabs.sort(reverse=True)
    print("Using:", sprint_tabs[0][1])
    return sprint_tabs[0][1]

def read_tab(service, tab):
    r = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'").execute()
    return r.get("values",[])

def safe(row, i):
    try:
        v = row[i]
        s = str(v).strip() if v else ""
        return "" if s.lower() in ("nan","false","none") else s
    except:
        return ""

def detect_section(text):
    tl = text.lower().strip()
    for keyword, pod_id in SECTION_MAP:
        if keyword in tl:
            return pod_id
    return None

def parse(rows):
    items = []
    qa_items = []
    current_pod = "engage"

    for row in rows[1:]:
        owner   = safe(row, 0)
        feature = safe(row, 1)
        notes   = safe(row, 12)
        assignee= safe(row, 27)
        status  = safe(row, 28)
        jira    = safe(row, 29)
        itype   = safe(row, 25)

        # Section header: owner has text, feature is empty
        if owner and not feature:
            pod = detect_section(owner)
            if pod:
                current_pod = pod
            continue

        if not feature:
            continue

        # Skip noise
        if feature in SKIP_FEATURES:
            continue
        fl = feature.lower()
        if any(kw in fl for kw in SKIP_PARTIAL):
            continue

        # Must be a real item — has type, jira, or status
        has_type   = itype in ("Task","Story","Bug")
        has_jira   = bool(jira)
        has_status = bool(status)
        if not (has_type or has_jira or has_status):
            continue

        # Blocker detection
        is_blocked = any(x in notes for x in [
            "BLOCKED","TSD is pending","waiting from product",
            "waiting for clarity","Approach to be finalised","TSD Completed" # TSD completed = was blocked, now unblocked
        ])
        # Only mark as blocked if status hasn't moved past To Do
        display_status = status or "To Do"
        if is_blocked and display_status == "To Do":
            blocker_note = notes.replace("\n"," ").strip()
        else:
            is_blocked = False
            blocker_note = ""

        item = {
            "pod":      current_pod,
            "feature":  feature.replace("\n"," ").strip(),
            "jira":     jira or "-",
            "status":   display_status,
            "assignee": assignee or "-",
            "notes":    blocker_note,
        }

        if current_pod == "qa_releases":
            qa_items.append(item)
        else:
            items.append(item)

    return items, qa_items

def build_pods(items):
    pod_items = {pid: [] for pid in POD_ORDER}
    for i in items:
        if i["pod"] in pod_items:
            pod_items[i["pod"]].append(i)
    pods = []
    for pid in POD_ORDER:
        cfg = POD_CONFIG[pid]
        pods.append({
            "id":     pid,
            "name":   cfg["name"],
            "color":  cfg["color"],
            "headBg": cfg["headBg"],
            "lead":   cfg["lead"],
            "note":   cfg["note"],
            "team":   STATIC_TEAMS.get(pid,[]),
            "items":  pod_items[pid],
        })
    return pods

def calc_stats(items, qa_items):
    all_items = items + qa_items
    total   = len(all_items)
    done    = sum(1 for i in all_items if "done" in i["status"].lower() or i["status"]=="In QA")
    prog    = sum(1 for i in all_items if "progress" in i["status"].lower() or "review" in i["status"].lower())
    blocked = sum(1 for i in all_items if "block" in i["status"].lower())
    return {"total":total,"done":done,"inProgress":prog,"blocked":blocked,"notStarted":total-done-prog-blocked}

def main():
    svc = get_service()
    tab = find_latest_tab(svc)
    rows = read_tab(svc, tab)
    items, qa_items = parse(rows)
    pods = build_pods(items)

    print(f"Total sprint items: {len(items)}, QA/Release items: {len(qa_items)}")
    for p in pods:
        print(f"  {p['name']}: {len(p['items'])} items")
    print(f"  QA & Releases: {len(qa_items)} items")

    m = re.search(r"(\d+)\s+(.+)", tab, re.IGNORECASE)
    data = {
        "generatedAt":  datetime.now(timezone.utc).isoformat(),
        "sprintNumber": m.group(1) if m else "?",
        "sprintDates":  m.group(2).strip() if m else tab,
        "sheetName":    tab,
        "stats":        calc_stats(items, qa_items),
        "pods":         pods,
        "qaItems":      qa_items,
        "teamUpdates":  TEAM_UPDATES,
    }

    with open("data.json","w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    data_str = json.dumps(data, ensure_ascii=True)
    html = open("index.html").read()
    html = re.sub(r'var D = .*?; /\* DATA_PLACEHOLDER \*/', 'var D = null; /* DATA_PLACEHOLDER */', html)
    html = html.replace("var D = null; /* DATA_PLACEHOLDER */", f"var D = {data_str};")
    open("index.html","w").write(html)
    print("Done.")

if __name__ == "__main__":
    main()
