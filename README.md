# Bihar Power Demand Status Dashboard

A light, single-page dashboard of Bihar's power demand position, refreshed automatically every 30 minutes.

## What it shows

**Right now** (SLDC Bihar SCADA)
- Demand met (MW), with the SBPDCL / NBPDCL split and today's peak so far
- Actual drawl vs drawl schedule, with over/under-drawl deviation
- State's own generation (thermal share, railway drawl)
- Grid frequency against the IEGC band (49.90–50.05 Hz)
- Today's load curve: demand, drawl and schedule
- DISCOM-wise demand, net drawl, net schedule and deviation

**Previous day** (SLDC previous-day report)
- Maximum and minimum demand with times, min/max ratio, peak vs record
- Availability at peak and margin, frequency at peak, solar energy
- SBPDCL / NBPDCL share at peak and at minimum

**Daily trend**: daily max and min demand, built up one day at a time from the first run (30 days / 90 days / 1 year / all).

**Long-term picture** (official public figures): annual energy requirement vs supplied (CEA), all-time peak demand met (CEA, or a higher peak SLDC has reported since), per-capita consumption, connections and commissioned capacity (Bihar Economic Survey), and district-wise consumption 2018-19 to 2024-25 (search and sort).

## How it works

```
GitHub Actions (every 30 min)  ->  scripts/fetch_data.py  ->  data/*.json, data/*.csv  ->  index.html (GitHub Pages)
```

| File | Contents |
|---|---|
| `data/live.json` | Latest SCADA reading, previous-day report, today's curve |
| `data/history/YYYY-MM.csv` | Every SCADA reading collected, one file per month |
| `data/daily.csv` | One row per day: max/min demand, times, DISCOM shares, availability |
| `data/reference.json` | Official yearly figures with their sources. Edited by hand; the collector never changes it |

The collector uses only the Python standard library. If SLDC does not answer, the last good reading is kept and the page shows **Delayed** or **Not updated**; it never shows made-up numbers.

## Setup (one time)

1. **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, folder `/ (root)` → Save.
   GitHub Pages on a **private** repository needs a paid GitHub plan; otherwise make the repository public.
2. **Settings → Actions → General → Workflow permissions** → *Read and write permissions* → Save.
3. **Actions → Update power demand data → Run workflow** once to start collection.

Actions usage: about 1 minute per run, ~1,450 minutes a month. Free on public repositories; on a private repository this uses most of the 2,000 free minutes. To reduce it, change the cron in `.github/workflows/update-data.yml` to hourly (`7 * * * *`).

## Sources

- Live and previous-day data: State Load Despatch Centre, Bihar (BSPTCL), public SCADA API `sldc.bsptcl.co.in:8086/api`
- Energy requirement vs supplied: CEA data in the Ministry of Power's Lok Sabha reply, [PIB, 29 Jan 2026](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2220087)
- Record peak demand: [CEA Peak Power Supply Position, July 2026](https://cea.nic.in/wp-content/uploads/power_supply/2026/07/Peak_July_26_Revised.pdf)
- Per-capita consumption, connections, commissioned capacity: Bihar Economic Survey 2025-26 (and 2024-25)
- District-wise consumption: Bihar Economic Survey table as compiled by BiharInfraTales (not yet checked line by line)

## Updating the official figures

Open `data/reference.json` on GitHub, click the pencil icon, change the number and its `source`, and commit. The page picks it up on the next load. When the Bihar Economic Survey 2026-27 or a new CEA annual figure comes out, add a row there.
