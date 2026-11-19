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

**Long-term picture** (yearly reference data): annual energy requirement vs availability, per-capita consumption, grid infrastructure, generation portfolio, rooftop solar, and district-wise consumption 2018-19 to 2024-25 (search and sort).

## How it works

```
GitHub Actions (every 30 min)  ->  scripts/fetch_data.py  ->  data/*.json, data/*.csv  ->  index.html (GitHub Pages)
```

| File | Contents |
|---|---|
| `data/live.json` | Latest SCADA reading, previous-day report, today's curve |
| `data/history/YYYY-MM.csv` | Every SCADA reading collected, one file per month |
| `data/daily.csv` | One row per day: max/min demand, times, DISCOM shares, availability |
| `data/reference.json` | Yearly datasets, refreshed once a day |

The collector uses only the Python standard library. If SLDC does not answer, the last good reading is kept and the page shows **Delayed** or **Not updated**; it never shows made-up numbers.

## Setup (one time)

1. **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, folder `/ (root)` → Save.
   GitHub Pages on a **private** repository needs a paid GitHub plan; otherwise make the repository public.
2. **Settings → Actions → General → Workflow permissions** → *Read and write permissions* → Save.
3. **Actions → Update power demand data → Run workflow** once to start collection.

Actions usage: about 1 minute per run, ~1,450 minutes a month. Free on public repositories; on a private repository this uses most of the 2,000 free minutes. To reduce it, change the cron in `.github/workflows/update-data.yml` to hourly (`7 * * * *`).

## Sources

- Live and previous-day data: State Load Despatch Centre, Bihar (BSPTCL), public SCADA API `sldc.bsptcl.co.in:8086/api`
- Reference data: [BiharInfraTales energy dashboard](https://biharinfratales.com/energy), CC BY 4.0
