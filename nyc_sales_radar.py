#!/usr/bin/env python3
"""
NYC Sales Radar  (v2 — broad, multi-industry, auto-token-resolving)
-------------------------------------------------------------------
Polls startup ATS boards (Greenhouse / Lever) for newly posted SALES roles,
filters to titles realistic for an early-career seller, scopes to NYC/remote-US,
diffs against the last run, prints/emails only the NEW roles.

Key v2 change: you no longer hunt board tokens. Just list company names.
The resolver checks Greenhouse then Lever and finds the board automatically.
Adding a company = add ONE line to SEED.

Stdlib only. No pip.
    python nyc_sales_radar.py          # live: resolves boards + hits real APIs
    python nyc_sales_radar.py --demo   # offline: sample postings, proves filter
    python nyc_sales_radar.py --resolve   # live: just test which slugs resolve
"""

import json, re, sys, os, smtplib, urllib.request, urllib.error
from email.mime.text import MIMEText
from datetime import datetime

# ---------------------------------------------------------------------------
# SEED  =  (company, slug, industry).  Slug is the careers-board guess
# (usually the lowercased company name). The resolver auto-detects Greenhouse
# vs Lever at runtime and reports any slug it can't find — so wrong guesses are
# self-correcting, not silent. This is your wide net across ALL industries;
# the Form D layer (next build) ranks it by who raised most recently = youngest.
# ---------------------------------------------------------------------------
SEED = [
    # ---- fintech ----
    ("Ramp","ramp","fintech"), ("Alloy","alloy","fintech"), ("Rho","rho","fintech"),
    ("Lithic","lithic","fintech"), ("Unit","unit","fintech"), ("Ocrolus","ocrolus","fintech"),
    ("Nova Credit","novacredit","fintech"), ("Capitolis","capitolis","fintech"),
    ("Esusu","esusu","fintech"), ("Stash","stash","fintech"), ("Current","current","fintech"),
    # ---- AI ----
    ("Hebbia","hebbia","ai"), ("Rogo","rogo","ai"), ("Runway","runwayml","ai"),
    ("Captions","captions","ai"), ("Hyperscience","hyperscience","ai"),
    ("EliseAI","eliseai","ai"), ("Yurts","yurts","ai"), ("Tomorrow.io","tomorrowio","ai"),
    # ---- devtools / infra ----
    ("Cockroach Labs","cockroachlabs","devtools"), ("Pinecone","pinecone","devtools"),
    ("Clay","clay","devtools"), ("Dagster","dagsterlabs","devtools"),
    ("Fingerprint","fingerprint","devtools"), ("Vercel","vercel","devtools"),
    # ---- healthtech ----
    ("Cedar","cedar","healthtech"), ("Spring Health","springhealth","healthtech"),
    ("Ro","ro","healthtech"), ("Maven Clinic","mavenclinic","healthtech"),
    ("Alma","alma","healthtech"), ("K Health","khealth","healthtech"),
    ("Cityblock Health","cityblock","healthtech"), ("Capsule","capsule","healthtech"),
    # ---- consumer / commerce SaaS ----
    ("Attentive","attentive","commerce"), ("Movable Ink","movableink","commerce"),
    ("Bluecore","bluecore","commerce"), ("Yotpo","yotpo","commerce"),
    ("Caraway","carawayhome","consumer"), ("Hungryroot","hungryroot","consumer"),
    ("Daily Harvest","dailyharvest","consumer"), ("Bombas","bombas","consumer"),
    # ---- proptech / logistics ----
    ("VTS","vts","proptech"), ("Latch","latch","proptech"), ("Veho","veho","logistics"),
    ("Stord","stord","logistics"),
    # ---- vertical / B2B SaaS ----
    ("Justworks","justworks","b2b"), ("Monday.com","mondaycom","b2b"),
    ("DoubleVerify","doubleverify","b2b"), ("MNTN","mntn","b2b"),
    ("Namely","namely","b2b"), ("Andela","andela","b2b"),
    # ---- climate ----
    ("Crux","cruxclimate","climate"), ("David Energy","davidenergy","climate"),
    ("Sealed","sealed","climate"), ("BlocPower","blocpower","climate"),
    # add your own below — just (Name, slug, industry); resolver finds the board
]

# ---------------------------------------------------------------------------
# REALISM FILTER — keeps it to roles a 25yo w/ ~1yr selling can actually land
# ---------------------------------------------------------------------------
EXCLUDE = ["vp","vice president","svp","evp","head of","director","chief"," cro",
           "regional sales manager","sales manager","team lead","people manager",
           "partner","principal"]
CORE = ["founding","account executive","sdr","bdr","sales development",
        "business development representative","business development rep","gtm",
        "go-to-market","sales associate","sales representative","mid-market",
        "mid market","smb","commercial account","account manager"]
STRETCH = ["enterprise account executive","senior account executive","senior ae",
           "strategic account","sales engineer","solutions engineer"]
AE_BOUNDARY = re.compile(r"\bae\b")

def classify_fit(title):
    t = title.lower()
    is_acct_mgr = "account manager" in t
    if not is_acct_mgr:
        for kw in EXCLUDE:
            if kw in t: return None
    for kw in STRETCH:
        if kw in t: return "stretch"
    for kw in CORE:
        if kw in t: return "core"
    if AE_BOUNDARY.search(t): return "core"
    return None

def location_ok(loc):
    if not loc: return True
    l = loc.lower()
    drop = ["london","san francisco","sf,","bay area","austin","denver","toronto",
            "berlin","paris","bangalore","tel aviv","dublin","los angeles","chicago",
            "boston","miami","seattle","remote - eu","emea","apac"]
    if any(d in l for d in drop) and not any(k in l for k in ["new york","nyc"]):
        return False
    return True

# ---------------------------------------------------------------------------
# FETCH + AUTO-RESOLVE
# ---------------------------------------------------------------------------
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent":"nyc-sales-radar"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def _gh_jobs(token):
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    return [{"id":f"gh-{token}-{j['id']}","title":j.get("title",""),
             "location":(j.get('location') or {}).get('name',""),
             "url":j.get("absolute_url","")} for j in d.get("jobs",[])]

def _lv_jobs(token):
    d = _get(f"https://api.lever.co/v0/postings/{token}?mode=json")
    out=[]
    for j in d:
        c=j.get("categories",{}) or {}
        out.append({"id":f"lv-{token}-{j.get('id')}","title":j.get("text",""),
                    "location":c.get("location",""),"url":j.get("hostedUrl","")})
    return out

def resolve_and_fetch(company, slug):
    """Try Greenhouse, then Lever. Return (jobs, ats) or raise."""
    try:
        jobs=_gh_jobs(slug)
        if jobs is not None: return jobs,"greenhouse"
    except urllib.error.HTTPError as e:
        if e.code not in (404,): raise
    jobs=_lv_jobs(slug)
    return jobs,"lever"

# ---------------------------------------------------------------------------
# STATE / DIGEST / EMAIL
# ---------------------------------------------------------------------------
STATE_FILE="seen_roles.json"
def load_seen():
    return set(json.load(open(STATE_FILE))) if os.path.exists(STATE_FILE) else set()
def save_seen(ids): json.dump(sorted(ids), open(STATE_FILE,"w"))

def gather(demo=False):
    if demo: return DEMO_POSTINGS, []
    rows, failed = [], []
    for company, slug, industry in SEED:
        try:
            jobs, ats = resolve_and_fetch(company, slug)
            for j in jobs:
                j["company"]=company; j["industry"]=industry
            rows.extend(jobs)
        except Exception as e:
            failed.append((company, slug, str(e)))
    return rows, failed

def filter_roles(rows):
    hits=[]
    for r in rows:
        fit=classify_fit(r["title"])
        if fit and location_ok(r["location"]):
            r["fit"]=fit; hits.append(r)
    return hits

def digest(new_hits, failed):
    L=[f"NYC SALES RADAR — {datetime.now():%a %b %d}  ({len(new_hits)} new)","="*52]
    if not new_hits:
        L.append("No new sales roles since last run.")
    for tier,label in [("core","CORE  (go for these)"),
                       ("stretch","STRETCH (a push, but reachable)")]:
        th=[h for h in new_hits if h["fit"]==tier]
        if th:
            L.append(f"\n{label}"); L.append("-"*52)
            for h in sorted(th, key=lambda x:(x["industry"],x["company"])):
                L.append(f"  [{h['industry']:<10}] {h['company']:<16} {h['title']}")
                L.append(f"  {'':<13} {h['location']}  {h['url']}")
    if failed:
        L.append(f"\n[!] {len(failed)} slugs didn't resolve — fix or drop them:")
        for c,s,_ in failed: L.append(f"    {c} ({s})")
    return "\n".join(L)

def maybe_email(body):
    if not os.getenv("SMTP_HOST"): return
    m=MIMEText(body); m["Subject"]=f"NYC Sales Radar — {datetime.now():%b %d}"
    m["From"]=os.environ["SMTP_USER"]; m["To"]=os.environ["EMAIL_TO"]
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT","465"))) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(m)

def main():
    if "--resolve" in sys.argv:
        for company, slug, _ in SEED:
            try: jobs,ats=resolve_and_fetch(company,slug); print(f"OK   {company:<18}{ats:<11}{len(jobs)} roles")
            except Exception as e: print(f"MISS {company:<18}{slug}  ({e})")
        return
    demo="--demo" in sys.argv
    rows, failed = gather(demo=demo)
    hits=filter_roles(rows)
    seen=set() if demo else load_seen()
    new_hits=[h for h in hits if h["id"] not in seen]
    out=digest(new_hits, failed); print(out)
    if not demo:
        save_seen(seen | {h["id"] for h in hits}); maybe_email(out)

DEMO_POSTINGS=[
 {"company":"Hebbia","industry":"ai","id":"d1","title":"Founding Account Executive","location":"New York, NY","url":"https://ex/1"},
 {"company":"Cedar","industry":"healthtech","id":"d2","title":"Sales Development Representative","location":"New York","url":"https://ex/2"},
 {"company":"Attentive","industry":"commerce","id":"d3","title":"Mid-Market Account Executive","location":"New York, NY","url":"https://ex/3"},
 {"company":"Rho","industry":"fintech","id":"d4","title":"SDR","location":"Remote - US","url":"https://ex/4"},
 {"company":"Pinecone","industry":"devtools","id":"d5","title":"VP of Sales","location":"New York, NY","url":"https://ex/5"},
 {"company":"VTS","industry":"proptech","id":"d6","title":"Sales Manager","location":"New York, NY","url":"https://ex/6"},
 {"company":"Runway","industry":"ai","id":"d7","title":"Sales Engineer","location":"New York, NY","url":"https://ex/7"},
 {"company":"Crux","industry":"climate","id":"d8","title":"Business Development Representative","location":"New York, NY","url":"https://ex/8"},
 {"company":"Spring Health","industry":"healthtech","id":"d9","title":"Account Executive","location":"San Francisco, CA","url":"https://ex/9"},
 {"company":"Clay","industry":"devtools","id":"d10","title":"Account Manager","location":"New York, NY","url":"https://ex/10"},
]
if __name__=="__main__": main()
