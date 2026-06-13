#!/usr/bin/env python3
"""
Daily runner — builds a styled HTML email with two sections:
  1. FRESH FUNDED & HIRING (private) — NY companies that filed a Form D recently,
     auto-resolved to their ATS board, showing the round size + date + gettable role.
  2. ROLE COVERAGE RADAR — the curated company list, grouped by industry, tiered
     core/stretch. Dedupes against the shared 'seen' state. Sends ONE email.

    python run_daily.py          # live: full run + HTML email (needs SMTP_* env)
    python run_daily.py --demo   # offline: writes preview.html you can open
"""
import os, sys, smtplib, html
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import nyc_sales_radar as R
import form_d as FD

# ---------------------------------------------------------------------------
# DATA: funded private companies -> resolve ATS -> NEW gettable sales roles
# ---------------------------------------------------------------------------
def funded_and_hiring(raises, seen):
    out=[]; ids=set()
    for r in raises:
        try:
            jobs,_=R.resolve_and_fetch(r["company"], FD.slugify(r["company"]))
        except Exception:
            continue  # no public ATS board -> skip
        for j in jobs:
            fit=R.classify_fit(j["title"])
            if fit and R.location_ok(j["location"]):
                ids.add(j["id"])
                if j["id"] in seen: continue
                out.append({"company":r["company"], "amount":r["amount"],
                            "date":r["date"], "industry":r["industry"],
                            "title":j["title"], "location":j["location"],
                            "url":j["url"], "fit":fit})
    out.sort(key=lambda x:(x["date"], x["amount"]), reverse=True)
    return out, ids

# ---------------------------------------------------------------------------
# HTML EMAIL  (inline styles only — required for Gmail/email clients)
# ---------------------------------------------------------------------------
GREEN="#16a34a"; AMBER="#d97706"; BLUE="#1d4ed8"; INK="#111827"; MUTE="#6b7280"

def _esc(s): return html.escape(str(s or ""))

def _role_row(item, show_round=False):
    accent = GREEN if item["fit"]=="core" else AMBER
    dot = (f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
           f'background:{accent};margin-right:8px;vertical-align:middle;"></span>')
    fit_label = "core" if item["fit"]=="core" else "stretch"
    badge=""
    if show_round:
        badge=(f'<span style="background:#eff6ff;color:{BLUE};border-radius:999px;'
               f'padding:2px 10px;font-size:12px;font-weight:600;white-space:nowrap;">'
               f'{_esc(FD.fmt_amt(item["amount"]))} · {_esc(item["date"])}</span>')
    head=(f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
          f'<td style="font-weight:600;font-size:15px;color:{INK};">{_esc(item["company"])}'
          f'<span style="color:{MUTE};font-weight:400;font-size:12px;"> · {_esc(item["industry"])}</span></td>'
          f'<td align="right">{badge}</td></tr></table>')
    role=(f'<div style="margin-top:6px;font-size:14px;">{dot}'
          f'<a href="{_esc(item["url"])}" style="color:{INK};text-decoration:none;font-weight:500;">{_esc(item["title"])}</a>'
          f'<span style="color:{MUTE};"> — {_esc(item["location"])} '
          f'<span style="font-size:11px;color:{accent};">({fit_label})</span></span></div>')
    return (f'<div style="border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin:8px 0;'
            f'background:#ffffff;">{head}{role}</div>')

def build_html(funded, radar_hits, failed):
    n_f, n_r = len(funded), len(radar_hits)
    parts=[f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
           f'max-width:660px;margin:0 auto;padding:8px;color:{INK};background:#f9fafb;">']
    parts.append(f'<div style="padding:16px 4px 4px;">'
                 f'<div style="font-size:22px;font-weight:700;">NYC Sales Radar</div>'
                 f'<div style="color:{MUTE};font-size:13px;margin-top:2px;">'
                 f'{datetime.now():%A, %B %d} · {n_f} funded openings · {n_r} radar roles</div></div>')

    # Section 1 — funded & hiring
    parts.append(f'<div style="font-size:15px;font-weight:700;margin:18px 4px 4px;">'
                 f'💰 Freshly funded &amp; hiring (private)</div>')
    if funded:
        for it in funded: parts.append(_role_row(it, show_round=True))
    else:
        parts.append(f'<div style="color:{MUTE};font-size:13px;padding:4px;">'
                     f'No newly funded private companies with gettable sales roles today.</div>')

    # Section 2 — radar coverage, grouped by industry
    parts.append(f'<div style="font-size:15px;font-weight:700;margin:22px 4px 4px;">'
                 f'📡 Role coverage radar</div>')
    if radar_hits:
        by_ind={}
        for h in radar_hits: by_ind.setdefault(h["industry"],[]).append(h)
        for ind in sorted(by_ind):
            parts.append(f'<div style="font-size:12px;font-weight:600;color:{MUTE};'
                         f'text-transform:uppercase;letter-spacing:.04em;margin:12px 4px 2px;">{_esc(ind)}</div>')
            for h in sorted(by_ind[ind], key=lambda x:(x["fit"]!="core", x["company"])):
                parts.append(_role_row(h, show_round=False))
    else:
        parts.append(f'<div style="color:{MUTE};font-size:13px;padding:4px;">No new radar roles today.</div>')

    # footer
    foot=f'<div style="color:{MUTE};font-size:11px;margin:20px 4px;line-height:1.5;">' \
         f'Green dot = core fit · amber = stretch. Funding from SEC Form D filings (private placements).'
    if failed:
        foot+=f'<br>{len(failed)} company slug(s) did not resolve — clean these up: ' + \
              ", ".join(_esc(c) for c,_,_ in failed)
    foot+='</div></div>'
    parts.append(foot)
    return "".join(parts)

def build_text(funded, radar_hits):
    L=[f"NYC SALES RADAR — {datetime.now():%b %d}",
       f"{len(funded)} funded openings · {len(radar_hits)} radar roles","",
       "FRESHLY FUNDED & HIRING (PRIVATE)"]
    if funded:
        for it in funded:
            L.append(f"  [{it['industry']}] {it['company']} — raised {FD.fmt_amt(it['amount'])} ({it['date']})")
            L.append(f"     {it['title']} — {it['location']} ({it['fit']})")
            L.append(f"     {it['url']}")
    else: L.append("  (none today)")
    L+=["","ROLE COVERAGE RADAR"]
    for h in sorted(radar_hits, key=lambda x:(x["industry"], x["fit"]!="core", x["company"])):
        L.append(f"  [{h['industry']}] {h['company']} — {h['title']} — {h['location']} ({h['fit']})")
        L.append(f"     {h['url']}")
    return "\n".join(L)

def send(html_body, text_body):
    if not os.getenv("SMTP_HOST"):
        print("(no SMTP_* env set — not emailing)"); return
    msg=MIMEMultipart("alternative")
    msg["Subject"]=f"NYC Sales Radar — {datetime.now():%b %d}"
    msg["From"]=os.environ["SMTP_USER"]; msg["To"]=os.environ["EMAIL_TO"]
    msg.attach(MIMEText(text_body,"plain")); msg.attach(MIMEText(html_body,"html"))
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT","465"))) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(msg)

# ---------------------------------------------------------------------------
def main():
    if "--demo" in sys.argv:
        radar=[{**d,"fit":R.classify_fit(d["title"]) or "core"} for d in R.DEMO_POSTINGS
               if R.classify_fit(d["title"])]
        funded=[{"company":r["company"],"amount":r["amount"],"date":r["date"],
                 "industry":r["industry"],"title":"Account Executive","location":"New York, NY",
                 "url":"https://example.com","fit":"core"} for r in FD.DEMO]
        h=build_html(funded, radar, [])
        open("preview.html","w").write(h)
        print("Wrote preview.html — open it in a browser to see the layout."); return

    rows, failed = R.gather(demo=False)
    radar_hits=R.filter_roles(rows)
    seen=R.load_seen()
    new_radar=[h for h in radar_hits if h["id"] not in seen]

    try:
        raises=FD.recent_ny_raises(days=90)
        funded, fids = funded_and_hiring(raises, seen)
    except Exception as e:
        print(f"Form D step skipped: {e}"); funded, fids = [], set()

    html_body=build_html(funded, new_radar, failed)
    text_body=build_text(funded, new_radar)
    print(text_body)
    R.save_seen(seen | {h["id"] for h in radar_hits} | fids)
    send(html_body, text_body)

if __name__=="__main__": main()
