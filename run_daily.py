#!/usr/bin/env python3
"""
Daily runner — fires the curated radar + Form D discovery, dedupes against the
shared 'seen' state, and sends ONE combined email. This is what the cron calls.

    python run_daily.py          # live: full run + email (needs SMTP_* env vars)
    python run_daily.py --demo   # offline: assembles the combined digest shape
"""
import os, sys, smtplib
from datetime import datetime
from email.mime.text import MIMEText
import nyc_sales_radar as R
import form_d as FD

def discover_block(raises, seen):
    """Funded NY companies -> auto-resolve ATS -> realistic, NEW sales roles."""
    lines=["FUNDED + HIRING + GETTABLE", "="*52]
    ids=set(); found=False
    for r in raises:
        try:
            jobs,_=R.resolve_and_fetch(r["company"], FD.slugify(r["company"]))
        except Exception:
            continue  # no public board -> skip
        for j in jobs:
            fit=R.classify_fit(j["title"])
            if fit and R.location_ok(j["location"]):
                ids.add(j["id"])
                if j["id"] in seen: continue
                found=True
                tag="*" if fit=="core" else "."
                lines.append(f"  {tag} {r['date']}  raised {FD.fmt_amt(r['amount'])}  "
                             f"[{r['industry']}] {r['company']}")
                lines.append(f"      {j['title']} — {j['location']}")
                lines.append(f"      {j['url']}")
    if not found: lines.append("  Nothing new in the funded cohort today.")
    return "\n".join(lines), ids

def send(body):
    if not os.getenv("SMTP_HOST"):
        print("\n(no SMTP_* env set — printed only, no email sent)"); return
    m=MIMEText(body); m["Subject"]=f"NYC Sales Radar — {datetime.now():%b %d}"
    m["From"]=os.environ["SMTP_USER"]; m["To"]=os.environ["EMAIL_TO"]
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT","465"))) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(m)

def main():
    demo="--demo" in sys.argv
    if demo:
        rows, failed = R.DEMO_POSTINGS, []
        for d in rows: d.setdefault("industry","other")
        hits=R.filter_roles(rows); seen=set(); new=hits
        block1=R.digest(new, failed)
        for d in FD.DEMO: d.setdefault("url","")
        block2 = "FUNDED (ranked) — discovery resolves these to ATS live\n"+"="*52+"\n" + \
                 "\n".join(f"  {r['date']}  {FD.fmt_amt(r['amount']):>8}  [{r['industry']}] {r['company']}"
                           for r in FD.DEMO)
        print(block1+"\n\n"+block2); return

    rows, failed = R.gather(demo=False)
    hits=R.filter_roles(rows)
    seen=R.load_seen()
    new=[h for h in hits if h["id"] not in seen]
    block1=R.digest(new, failed)

    raises=FD.recent_ny_raises(days=90)
    block2, disc_ids = discover_block(raises, seen)

    body=block1+"\n\n"+block2
    print(body)
    R.save_seen(seen | {h["id"] for h in hits} | disc_ids)
    send(body)

if __name__=="__main__": main()
