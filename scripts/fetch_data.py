#!/usr/bin/env python3
"""
Bihar Power Demand Status - data collector.

Runs on a schedule in GitHub Actions (see .github/workflows/update-data.yml).
Uses only the Python standard library.

Sources
  1. Bihar SLDC (BSPTCL) public SCADA API - live state demand, DISCOM split,
     drawl vs schedule, state generation, frequency, previous-day max/min.
       https://sldc.bsptcl.co.in:8086/api
  Yearly reference figures live in data/reference.json. That file is
  hand-curated from official public sources (CEA, PIB, Bihar Economic Survey)
  and is never overwritten by this script.

Outputs (all inside data/)
  live.json              latest SCADA reading + previous-day report + today's curve
  history/YYYY-MM/YYYY-MM-DD.csv   one row per SCADA reading, one file per day
  daily.csv              one row per day: previous-day max / min demand etc.
  reference.json         official yearly figures (edited by hand, not touched here)
"""

import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST_DIR = os.path.join(DATA, "history")

SLDC = "https://sldc.bsptcl.co.in:8086/api"
SLDC_URLS = {
    "latest": f"{SLDC}/SCADA/Get/StateWiseRegionStatistics",
    "series": f"{SLDC}/SCADA/Get/GetAllSCADAData",
    "prevday": f"{SLDC}/pspreportpsp/Get/pspreport_psp_regionalavailabilitydemands",
}
UA = "BiharPowerDemandDashboard/1.0 (+github.com/mdsbpdcl-hub)"

# Numeric SCADA fields kept in history / live
FIELDS = [
    "DemandMet", "NB_DEMAND_MET", "SB_DEMAND_MET",
    "Actual", "Scheduled", "Deviation",
    "NB_NET_DWL", "NB_NET_SCHD", "SB_NET_DWL", "SB_NET_SCHD",
    "StateGeneration", "ThermalGeneration", "RAILWAY_DRAWL", "Freq",
]


def log(*a):
    print("[fetch]", *a, file=sys.stderr)


# ---------------------------------------------------------------- HTTP
def _ctx(verify=True):
    """SSL context that still verifies the certificate but allows the legacy
    TLS renegotiation the SLDC server needs (OpenSSL 3 blocks it by default:
    'UNSAFE_LEGACY_RENEGOTIATION_DISABLED')."""
    ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _is_cert_error(e):
    r = getattr(e, "reason", e)
    return isinstance(r, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e)


def http_get(url, accept="application/json", timeout=30):
    """GET with retries. If the certificate chain cannot be verified (common on
    government hosts with an incomplete chain), retry without verification -
    this is a public, read-only data feed - and report it."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                return r.read().decode("utf-8", "replace"), True
        except Exception as e:  # noqa: BLE001
            last = e
            if _is_cert_error(e):
                break
        time.sleep(3 * (attempt + 1))
    else:
        raise last
    log("certificate not verifiable for", url, "-", last, "- retrying unverified")
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx(verify=False)) as r:
        return r.read().decode("utf-8", "replace"), False


def _strip_ns(tag):
    return tag.split("}", 1)[-1]


def _xml_to_py(el):
    kids = list(el)
    if not kids:
        nil = any(_strip_ns(k) == "nil" and v == "true" for k, v in el.attrib.items())
        return None if nil else (el.text or "").strip()
    # array if root name starts with ArrayOf or children share one tag
    tags = [_strip_ns(k.tag) for k in kids]
    if _strip_ns(el.tag).startswith("ArrayOf") or (len(kids) > 1 and len(set(tags)) == 1):
        return [_xml_to_py(k) for k in kids]
    return {_strip_ns(k.tag): _xml_to_py(k) for k in kids}


def parse_any(text):
    t = text.lstrip()
    if t.startswith("{") or t.startswith("["):
        return json.loads(t)
    if t.startswith("<"):
        return _xml_to_py(ET.fromstring(t))
    raise ValueError("Unrecognised response: " + t[:80])


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def scada_dt(d, t):
    """SCADA Date 'DDMMYY' + Time 'HHMMSS' -> aware IST datetime."""
    d = str(d if d is not None else "").split(".")[0].zfill(6)
    t = str(t if t is not None else "").split(".")[0].zfill(6)
    if not (re.fullmatch(r"\d{6}", d) and re.fullmatch(r"\d{6}", t)):
        return None
    try:
        return datetime(2000 + int(d[4:6]), int(d[2:4]), int(d[0:2]),
                        int(t[0:2]), int(t[2:4]), int(t[4:6]), tzinfo=IST)
    except ValueError:
        return None


def clean_reading(rec):
    if not isinstance(rec, dict):
        return None
    ts = scada_dt(rec.get("Date"), rec.get("Time"))
    if ts is None:
        return None
    out = {"ts": ts.isoformat()}
    for f in FIELDS:
        v = num(rec.get(f))
        out[f] = round(v, 2) if v is not None else None
    if out["Deviation"] is None and out["Actual"] is not None and out["Scheduled"] is not None:
        out["Deviation"] = round(out["Actual"] - out["Scheduled"], 2)
    return out


# ---------------------------------------------------------------- files
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


HIST_COLS = ["ts"] + FIELDS


def append_history(readings):
    """Append readings not already stored. Returns number added."""
    os.makedirs(HIST_DIR, exist_ok=True)
    by_day = {}
    for r in readings:
        by_day.setdefault(r["ts"][:10], []).append(r)
    added = 0
    for day, rows in by_day.items():
        path = os.path.join(HIST_DIR, day[:7], f"{day}.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        seen = set()
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                seen = {row["ts"] for row in csv.DictReader(f)}
        new = sorted((r for r in rows if r["ts"] not in seen), key=lambda r: r["ts"])
        if not new:
            continue
        exists = os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HIST_COLS, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerows(new)
        added += len(new)
    return added


def load_history_for(day_prefix):
    path = os.path.join(HIST_DIR, day_prefix[:7], f"{day_prefix[:10]}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [
            {k: (num(v) if k != "ts" else v) for k, v in row.items()}
            for row in csv.DictReader(f) if row["ts"].startswith(day_prefix)
        ]


DAILY_COLS = [
    "date", "max_demand_mw", "max_time", "max_nb_mw", "max_sb_mw",
    "max_availability_mw", "max_freq_hz", "min_demand_mw", "min_time",
    "min_nb_mw", "min_sb_mw", "min_availability_mw", "min_freq_hz",
    "energy_mu", "renewable_mu", "solar_mu",
]


def parse_prevday(data):
    if not isinstance(data, list) or not data:
        return None

    def pick(peak, typ):
        for e in data:
            if isinstance(e, dict) and str(e.get("Peak", "")).startswith(peak) and e.get("Type") == typ:
                return e.get("Value")
        return None

    def side(peak):
        return {
            "demand": num(pick(peak, "Demand Met")),
            "nb": num(pick(peak, "NB Share")),
            "sb": num(pick(peak, "SB Share")),
            "availability": num(pick(peak, "Availability")),
            "freq": num(pick(peak, "Frequency")),
            "time": pick(peak, "Time"),
        }

    return {
        "date": str(data[0].get("Date") or "")[:10],
        "max": side("Previous Day Max"),
        "min": side("Previous Day Min"),
        "energy_mu": num(pick("Day Energy", "Total Day Energy")),
        "renewable_mu": num(pick("Previous Day Renewable", "Total Renewable Energy")),
        "solar_mu": num(pick("Previous Day Renewable", "Solar Energy")),
    }


def append_daily(p):
    if not p or not p.get("date") or p["max"]["demand"] is None:
        return False
    path = os.path.join(DATA, "daily.csv")
    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    row = {
        "date": p["date"],
        "max_demand_mw": p["max"]["demand"], "max_time": p["max"]["time"],
        "max_nb_mw": p["max"]["nb"], "max_sb_mw": p["max"]["sb"],
        "max_availability_mw": p["max"]["availability"], "max_freq_hz": p["max"]["freq"],
        "min_demand_mw": p["min"]["demand"], "min_time": p["min"]["time"],
        "min_nb_mw": p["min"]["nb"], "min_sb_mw": p["min"]["sb"],
        "min_availability_mw": p["min"]["availability"], "min_freq_hz": p["min"]["freq"],
        "energy_mu": p["energy_mu"], "renewable_mu": p["renewable_mu"], "solar_mu": p["solar_mu"],
    }
    rows = [r for r in rows if r["date"] != row["date"]] + [{k: ("" if v is None else v) for k, v in row.items()}]
    rows.sort(key=lambda r: r["date"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_COLS)
        w.writeheader()
        w.writerows(rows)
    return True


# ---------------------------------------------------------------- main steps
def update_live():
    now = datetime.now(IST)
    live = read_json(os.path.join(DATA, "live.json"), {}) or {}
    errors = []
    tls_ok = True

    # 1) latest reading
    latest = None
    try:
        txt, ok = http_get(SLDC_URLS["latest"])
        tls_ok &= ok
        latest = clean_reading(parse_any(txt))
    except Exception as e:  # noqa: BLE001
        errors.append(f"latest: {e}")

    # 2) full-day SCADA series (best effort)
    series = []
    try:
        txt, ok = http_get(SLDC_URLS["series"], timeout=45)
        tls_ok &= ok
        data = parse_any(txt)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        series = [r for r in (clean_reading(x) for x in (data or [])) if r]
    except Exception as e:  # noqa: BLE001
        errors.append(f"series: {e}")

    readings = series + ([latest] if latest else [])
    added = append_history(readings) if readings else 0

    # 3) previous-day report
    prev = None
    try:
        txt, ok = http_get(SLDC_URLS["prevday"])
        tls_ok &= ok
        prev = parse_prevday(parse_any(txt))
        append_daily(prev)
    except Exception as e:  # noqa: BLE001
        errors.append(f"prevday: {e}")

    if latest is None and series:
        latest = max(series, key=lambda r: r["ts"])

    # today's curve = stored history for the reading's day (dedup by ts)
    day = (latest["ts"] if latest else now.isoformat())[:10]
    today = {r["ts"]: r for r in load_history_for(day)}
    for r in readings:
        if r["ts"].startswith(day):
            today[r["ts"]] = r
    curve = [
        {"ts": r["ts"], "demand": r["DemandMet"], "drawl": r["Actual"],
         "schedule": r["Scheduled"], "nb": r["NB_DEMAND_MET"], "sb": r["SB_DEMAND_MET"],
         "freq": r["Freq"]}
        for r in sorted(today.values(), key=lambda r: r["ts"]) if r.get("DemandMet") is not None
    ]

    if len(curve) > 300:
        last = curve[-1]
        seen_slots, thin = set(), []
        for p in curve:
            slot = p["ts"][11:15] + str(int(p["ts"][15]) // 5)  # HH:M + 5-min bucket
            if slot not in seen_slots:
                seen_slots.add(slot)
                thin.append(p)
        if thin[-1] is not last:
            thin.append(last)
        curve = thin

    out = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "Bihar SLDC (BSPTCL) SCADA - sldc.bsptcl.co.in",
        "tls_verified": tls_ok,
        "latest": latest or live.get("latest"),
        "latest_is_fresh": latest is not None,
        "previous_day": prev or live.get("previous_day"),
        "today": curve or live.get("today", []),
        "errors": errors,
    }
    write_json(os.path.join(DATA, "live.json"), out)
    log(f"latest={'ok' if latest else 'FAILED'} series={len(series)} added={added} "
        f"prev={'ok' if prev else 'FAILED'} errors={errors}")
    return latest is not None or prev is not None


if __name__ == "__main__":
    ok = update_live()
    # Never fail the workflow just because SLDC is briefly down;
    # live.json records the error and the page shows "Delayed".
    if not ok:
        log("SLDC unreachable this run; previous data kept")
    sys.exit(0)
