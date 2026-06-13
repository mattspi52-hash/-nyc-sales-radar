#!/usr/bin/env python3
"""
Form D Layer  —  the "younger than Ramp" signal + auto-discovery
----------------------------------------------------------------
Uses SEC EDGAR (free, no key) to find NY companies that filed a fresh private
raise (Form D) in the last N days, then:
  (a) RANKS them by recency + raise size  -> your youth/heat signal
  (b) DISCOVERS them into the radar: auto-resolves each company's ATS board and
      checks for realistic sales roles -> "funded AND hiring AND gettable"

Pairs with nyc_sales_radar.py (imports its resolver + realism filter).

    python form_d.py            # live: pull recent NY raises, rank them
    python form_d.py --discover # live: raises -> ATS -> sales roles (the combo)
    python form_d.py --demo     # offline: sample data, proves the pipeline

IMPORTANT (live use): SEC requires a real User-Agent with your email, and rate-
limits to ~10 req/s. Put your address in UA below or they'll 403 you.
"""
import json, sys, time, re, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

UA = {"User-Agent": "nyc-sales-radar mattspi52@gmail.com"}  # your contact for SEC

# EDGAR full-text search (JSON). q must be non-empty (empty -> 500), so we use
# 'securities' (every Form D is a "Notice of Exempt Offering of Securities", so
# this matches them all). locationCode=NY filters to NY filers server-side; we
# also re-check state from each filing as a safety net.
FTS = ("https://efts.sec.gov/LATEST/search-index"
       "?q=securities&forms=D&locationCode=NY"
       "&dateRange=custom&startdt={start}&enddt={end}&from=0")

MIN_AMOUNT = 1_000_000   # skip tiny/friends-and-family raises
CAP        = 60          # don't hammer EDGAR; newest N filings

# ---- Form D industry group -> your short tag --------------------------------
IND_MAP = {
    "technology":"tech","commercial":"b2b","health care":"healthtech",
    "biotechnology":"healthtech","banking":"fintech","financial":"fintech",
    "insurance":"fintech","retailing":"consumer","restaurants":"consumer",
    "manufacturing":"industrial","real estate":"proptech","energy":"climate",
}
def map_ind(s):
    s=(s or "").lower()
    for k,v in IND_MAP.items():
        if k in s: return v
    return "other"

def _get(url, parse="json"):
    req=urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        raw=r.read()
    return json.loads(raw) if parse=="json" else raw.decode(errors="ignore")

def _strip_ns(xml_text):
    # Form D XML namespaces are inconsistent; strip them for simple .find()
    return re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", xml_text, count=0)

def parse_form_d(cik, accession):
    acc=accession.replace("-","")
    url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"
    xml=_strip_ns(_get(url, parse="text"))
    root=ET.fromstring(xml)
    def txt(path):
        el=root.find(path); return el.text.strip() if el is not None and el.text else ""
    name=txt(".//primaryIssuer/entityName")
    state=txt(".//primaryIssuer/issuerAddress/stateOrCountry")
    industry=txt(".//offeringData/industryGroup/industryGroupType")
    sold=txt(".//offeringData/offeringSalesAmounts/totalAmountSold")
    is_amend=txt(".//offeringData/typeOfFiling/newOrAmendment/isAmendment")
    amt=int(sold) if sold.isdigit() else 0
    return {"company":name,"state":state,"industry":map_ind(industry),
            "amount":amt,"is_new":is_amend.lower()!="true","url":url}

def recent_ny_raises(days=90):
    end=datetime.now(); start=end-timedelta(days=days)
    url=FTS.format(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    data=_get(url)
    hits=data.get("hits",{}).get("hits",[])[:CAP]
    out=[]
    for h in hits:
        src=h.get("_source",{})
        cik=(src.get("ciks") or ["0"])[0]
        try: cik=str(int(cik))          # archives path wants the integer CIK
        except ValueError: continue
        accession=h.get("_id","").split(":")[0]
        date=src.get("file_date","")
        try:
            rec=parse_form_d(cik, accession); rec["date"]=date
            if rec["is_new"] and rec["amount"]>=MIN_AMOUNT and rec["state"]=="NY":
                out.append(rec)
        except Exception:
            pass
        time.sleep(0.12)  # be polite to EDGAR
    out.sort(key=lambda r:(r["date"], r["amount"]), reverse=True)
    return out

def slugify(name):
    s=re.sub(r"[^a-z0-9]","", name.lower())
    for suf in ("inc","llc","corp","co","ltd","holdings","technologies","labs"):
        if s.endswith(suf): s=s[:-len(suf)]
    return s

def fmt_amt(a): return f"${a/1e6:.1f}M" if a<1e9 else f"${a/1e9:.2f}B"

def print_ranked(raises):
    print(f"FRESH NY RAISES (last 90d, new offerings >$1M)  —  {len(raises)} found")
    print("="*60)
    for r in raises:
        print(f"  {r['date']}  {fmt_amt(r['amount']):>8}  [{r['industry']:<10}] {r['company']}")
    print("\nPaste-ready radar SEED lines (auto-guessed slugs — verify on resolve):")
    for r in raises:
        print(f'    ("{r["company"]}","{slugify(r["company"])}","{r["industry"]}"),')

def discover(raises):
    """The combo: funded -> auto-resolve ATS -> realistic sales roles."""
    from nyc_sales_radar import resolve_and_fetch, classify_fit, location_ok
    print("FUNDED  +  HIRING SALES  +  GETTABLE")
    print("="*60)
    found=False
    for r in raises:
        slug=slugify(r["company"])
        try:
            jobs,ats=resolve_and_fetch(r["company"], slug)
        except Exception:
            continue  # no public ATS board — skip silently
        for j in jobs:
            fit=classify_fit(j["title"])
            if fit and location_ok(j["location"]):
                found=True
                tag="✦" if fit=="core" else "·"
                print(f"  {tag} {r['date']}  raised {fmt_amt(r['amount'])}  "
                      f"[{r['industry']}] {r['company']}")
                print(f"      {j['title']}  —  {j['location']}")
                print(f"      {j['url']}")
    if not found:
        print("  No funded co's with open gettable sales roles in this batch.")

# ---- DEMO (offline) --------------------------------------------------------
DEMO=[
 {"company":"Northwind AI","slug":"northwindai","industry":"tech","amount":14_000_000,"date":"2026-06-09","is_new":True},
 {"company":"Cedarpost Health","slug":"cedarpost","industry":"healthtech","amount":8_500_000,"date":"2026-06-05","is_new":True},
 {"company":"Tessera Labs","slug":"tessera","industry":"fintech","amount":22_000_000,"date":"2026-05-30","is_new":True},
 {"company":"Juniper Logistics","slug":"juniper","industry":"logistics","amount":3_200_000,"date":"2026-05-21","is_new":True},
]
def main():
    if "--demo" in sys.argv:
        for d in DEMO: d.setdefault("url","")
        print_ranked(DEMO); return
    raises=recent_ny_raises(days=90)
    if "--discover" in sys.argv: discover(raises)
    else: print_ranked(raises)
if __name__=="__main__": main()
