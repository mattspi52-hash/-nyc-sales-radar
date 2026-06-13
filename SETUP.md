# NYC Sales Radar — setup (≈15 min, one time)

Files:
- `nyc_sales_radar.py` — curated company list + realism filter + ATS resolver
- `form_d.py` — SEC Form D: fresh NY raises + auto-discovery
- `run_daily.py` — runs both, dedupes, sends one email (what the cron calls)
- `.github/workflows/daily.yml` — the daily cron

## 1. Put your email in EDGAR's User-Agent
Open `form_d.py`, edit the `UA` line to your real email. SEC 403s generic agents.

## 2. Make a private GitHub repo
Drop all 4 files in, keeping `.github/workflows/daily.yml` in that path.
No `requirements.txt` needed — everything is Python stdlib.

## 3. Get an email app password (Gmail)
Google Account → Security → 2-Step Verification → App passwords → generate one.
(Regular password won't work with SMTP.)

## 4. Add repo secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `SMTP_HOST` = smtp.gmail.com
- `SMTP_PORT` = 465
- `SMTP_USER` = your_gmail@gmail.com
- `SMTP_PASS` = the app password from step 3
- `EMAIL_TO`  = where you want the digest (can be the same address)

## 5. Test it
Repo → Actions tab → nyc-sales-radar → "Run workflow" (manual trigger).
Check the run log + your inbox. After that it fires ~8am ET weekdays on its own.

## Maintaining it
- Add a company: one line in `SEED` in `nyc_sales_radar.py` → `(Name, slug, industry)`
- Check which slugs connect: `python nyc_sales_radar.py --resolve`
- Form D auto-prints paste-ready SEED lines for newly funded names
- Tune the realism filter: edit `CORE` / `STRETCH` / `EXCLUDE` keyword lists

## Known checks (because I couldn't hit the live APIs while building)
- A few seed slugs will 404 on first `--resolve` — fix or drop them (5 min)
- If Form D returns 0 live, open the printed EDGAR URL in a browser to confirm
  the param names; the script won't crash either way
