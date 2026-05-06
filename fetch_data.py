import json, os, re, time, urllib.request, urllib.error
from datetime import datetime, timezone

SPREADSHEET_ID  = os.environ.get("SPREADSHEET_ID", "1Sijbuj0mhLuT5svA7uKv02Ay3o0wlArB2kv0HYo1gCY")
GEMINI_KEY      = os.environ.get("GEMINI_API_KEY", "")

SECTION_MAP = [
    ("engage activities",       "engage"),
    ("hl tasks",                "hl_audio"),
    ("humyn labs — audio",      "hl_audio"),
    ("humyn labs - audio",      "hl_audio"),
    ("humyn labs — egocentric", "hl_ego"),
    ("humyn labs - egocentric", "hl_ego"),
    ("egocentric",              "hl_ego"),
    ("qa items",                "qa_releases"),
    ("to be released",          "qa_releases"),
    ("to be merged",            "qa_releases"),
    ("devops and security",     "devsec"),
    ("exlr8",                   "kstore"),
    ("kstore",                  "kstore"),
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

TEAM_UPDATES_FALLBACK = [
    {"type":"resigned",    "name":"Avish",                 "detail":"Father's accident. WFH 9-17 Apr. Tasks re-routed.", "status":"WFH 9-17 Apr"},
    {"type":"replacement", "name":"Akshay (HL Backend)",   "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"replacement", "name":"Shivam (GKMIT)",        "detail":"3-month notice. Replacement hiring underway.",       "status":"In Progress"},
    {"type":"info",        "name":"Raghav & Pankaj (GKMIT)","detail":"No replacement needed. Update to GKMIT pending.",  "status":"Update to GKMIT"},
]

SKIP_FEATURES = {"Shield Disable???","Features","Module Owner","Standalone app for audio collection","HL orchestrator","Cost and optimisation"}
SKIP_PARTIAL  = ["avoid copying recorder tool audio files","quest validation to happen via api","enhancements/optimisation to making the duplication","annotation events and attributes to be added","merge the collection and annotation hitl"]

def read_team_config():
    try:
        with open("team_config.json") as f:
            cfg = json.load(f)
        return cfg.get("teamUpdates", TEAM_UPDATES_FALLBACK), cfg.get("announcements", [])
    except Exception as ex:
        print(f"team_config.json not found or invalid — using fallback: {ex}")
        return TEAM_UPDATES_FALLBACK, []

def read_devsec_excel():
    excel_path = "devsec_backlog.xlsx"
    if not os.path.exists(excel_path):
        print("devsec_backlog.xlsx not found — skipping epic extraction")
        return []
    if not GEMINI_KEY:
        print("No GEMINI_API_KEY — skipping Excel parsing")
        return []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            row_data = [str(cell).strip() if cell is not None else "" for cell in row]
            if any(c for c in row_data):
                rows.append("\t".join(row_data))
        sheet_text = "\n".join(rows[:250])

        prompt = f"""Analyze this DevSec project backlog (raw Excel rows) and extract all EPICS — high-level initiatives, not individual tasks.

{sheet_text}

For each epic return:
- pri: "High", "Medium", or "Low"
- name: concise title (under 60 chars)
- desc: one sentence on what it achieves (under 100 chars)

Return ONLY a valid JSON array, no markdown or explanation:
[{{"pri":"High","name":"Epic name","desc":"Description"}}]

Rules: only top-level epics (not tasks), max 20 items, concise descriptions."""

        text = call_gemini(prompt, max_tokens=2000)
        text = re.sub(r'^```json\s*|^```\s*|```$', '', text, flags=re.MULTILINE).strip()
        epics = json.loads(text)
        print(f"DevSec epics extracted: {len(epics)}")
        return epics
    except Exception as ex:
        print(f"Gemini API error (epics): {ex}")
        return []

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
    sprint_tabs = [(int(re.search(r"SPRINT\s+(\d+)",t,re.I).group(1)),t)
                   for t in titles if re.search(r"SPRINT\s+(\d+)",t,re.I)]
    if not sprint_tabs:
        raise RuntimeError("No sprint tab found")
    sprint_tabs.sort(reverse=True)
    print("Using:", sprint_tabs[0][1])
    return sprint_tabs[0][1]

def read_tab(service, tab):
    r = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'").execute()
    return r.get("values",[])

def safe(row, i):
    try:
        v = row[i]
        s = str(v).strip() if v else ""
        return "" if s.lower() in ("nan","false","none") else s
    except: return ""

def detect_section(text):
    tl = text.lower().strip()
    for keyword, pod_id in SECTION_MAP:
        if keyword in tl:
            return pod_id
    return None

def parse(rows):
    items, qa_items = [], []
    current_pod = "engage"
    for row in rows[1:]:
        owner=safe(row,0); feature=safe(row,1); notes=safe(row,12)
        assignee=safe(row,27); status=safe(row,28); jira=safe(row,29); itype=safe(row,25)
        if owner and not feature:
            pod = detect_section(owner)
            if pod: current_pod = pod
            continue
        if not feature: continue
        if feature in SKIP_FEATURES: continue
        if any(kw in feature.lower() for kw in SKIP_PARTIAL): continue
        if not (itype in ("Task","Story","Bug") or jira or status): continue
        is_blocked = any(x in notes for x in ["BLOCKED","TSD is pending","waiting from product","waiting for clarity","Approach to be finalised"])
        display_status = status or "To Do"
        blocker_note = ""
        if is_blocked and display_status == "To Do":
            display_status = "Blocked"
            blocker_note = notes.replace("\n"," ").strip()
        item = {"pod":current_pod,"feature":feature.replace("\n"," ").strip(),"jira":jira or "-","status":display_status,"assignee":assignee or "-","notes":blocker_note}
        if current_pod == "qa_releases": qa_items.append(item)
        else: items.append(item)
    return items, qa_items

def build_pods(items):
    pod_items = {pid:[] for pid in POD_ORDER}
    for i in items:
        if i["pod"] in pod_items: pod_items[i["pod"]].append(i)
    pods = []
    for pid in POD_ORDER:
        cfg = POD_CONFIG[pid]
        pods.append({"id":pid,"name":cfg["name"],"color":cfg["color"],"headBg":cfg["headBg"],
                     "lead":cfg["lead"],"note":cfg["note"],"team":STATIC_TEAMS.get(pid,[]),"items":pod_items[pid]})
    return pods

def calc_stats(items, qa_items):
    all_items = items + qa_items
    total=len(all_items)
    done=sum(1 for i in all_items if "done" in i["status"].lower() or i["status"]=="In QA")
    prog=sum(1 for i in all_items if "progress" in i["status"].lower() or "review" in i["status"].lower())
    blocked=sum(1 for i in all_items if "block" in i["status"].lower())
    return {"total":total,"done":done,"inProgress":prog,"blocked":blocked,"notStarted":total-done-prog-blocked}

def call_gemini(prompt, max_tokens=1500):
    """Call Gemini Flash and return the response text. Retries on 429."""
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.5-flash:generateContent?key={GEMINI_KEY}")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens}
    }).encode()
    for attempt in range(3):
        if attempt:
            wait = 20 * attempt
            print(f"Rate limited — waiting {wait}s before retry {attempt+1}/3")
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read())
                return result["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                continue
            raise
    raise RuntimeError("Gemini API: max retries exceeded")

def claude_bandwidth_summary(items, qa_items):
    if not GEMINI_KEY:
        print("No GEMINI_API_KEY — skipping bandwidth summary")
        return []

    all_items = items + qa_items
    lines = []
    for i in all_items:
        lines.append(f"- [{i['pod']}] {i['feature']} | Assignee: {i['assignee']} | Status: {i['status']}"
                     + (f" | Jira: {i['jira']}" if i['jira'] != '-' else ""))
    sheet_text = "\n".join(lines)

    prompt = f"""You are analyzing a sprint planning sheet. Here are all work items for this sprint:

{sheet_text}

Create a bandwidth summary per person. For each unique person (ignore "-" or empty assignees):
- List their tasks (short names, max 6 words each)
- Estimate load: "light" (1-2 tasks), "moderate" (3-4 tasks), "heavy" (5+ tasks)
- Note if they own any blockers
- Note which pod they belong to

Return ONLY valid JSON, no markdown, no explanation:
[
  {{
    "name": "Person Name",
    "pod": "pod name",
    "load": "light|moderate|heavy",
    "taskCount": 3,
    "tasks": ["short task name", "another task"],
    "hasBlocker": false,
    "blockerNote": ""
  }}
]

Rules: combine slight name variations (e.g. "Yogesh" and "Yogesh Kumar" are the same), sort by load descending, skip "-" or "TBD", max 8 people."""

    try:
        text = call_gemini(prompt, max_tokens=1500)
        text = re.sub(r'^```json\s*|^```\s*|```$', '', text, flags=re.MULTILINE).strip()
        bandwidth = json.loads(text)
        print(f"Bandwidth summary: {len(bandwidth)} people")
        return bandwidth
    except Exception as ex:
        print(f"Gemini API error (bandwidth): {ex}")
        return []

def main():
    svc = get_service()
    tab = find_latest_tab(svc)
    rows = read_tab(svc, tab)
    items, qa_items = parse(rows)
    pods = build_pods(items)
    bandwidth = claude_bandwidth_summary(items, qa_items)
    team_updates, announcements = read_team_config()
    if GEMINI_KEY and bandwidth:
        time.sleep(15)  # avoid back-to-back rate limiting
    devsec_epics = read_devsec_excel()

    print(f"Items: {len(items)}, QA: {len(qa_items)}")
    for p in pods: print(f"  {p['name']}: {len(p['items'])} items")

    m = re.search(r"(\d+)\s+(.+)", tab, re.IGNORECASE)
    data = {
        "generatedAt":   datetime.now(timezone.utc).isoformat(),
        "sprintNumber":  m.group(1) if m else "?",
        "sprintDates":   m.group(2).strip() if m else tab,
        "sheetName":     tab,
        "stats":         calc_stats(items, qa_items),
        "pods":          pods,
        "qaItems":       qa_items,
        "bandwidth":     bandwidth,
        "teamUpdates":   team_updates,
        "announcements": announcements,
        "devsecEpics":   devsec_epics,
    }

    with open("data.json","w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    data_str = json.dumps(data, ensure_ascii=True)

    for html_file in ["index.html", "founder.html"]:
        if not os.path.exists(html_file):
            continue
        html = open(html_file).read()
        # Replace var D = <anything> on that line; use lambda to avoid re interpreting \u escapes in JSON
        replacement = f'var D = {data_str}; /* DATA_PLACEHOLDER */'
        html = re.sub(r'^var D = .*$', lambda _: replacement, html, flags=re.MULTILINE)
        open(html_file,"w").write(html)
        print(f"Updated {html_file}")

    print("Done.")

if __name__ == "__main__":
    main()