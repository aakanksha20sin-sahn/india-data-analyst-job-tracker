"""Collect live India analyst postings from JSearch (OpenWeb Ninja) into the same
local database as the Jooble collector (data/jobs.db, table live_jobs).

Run from your "Job Tracker" folder (where the .env file is):
    python collect_jsearch.py                  # up to 6 requests (one normal day)
    python collect_jsearch.py --max-requests 3

Needs  JSEARCH_KEY=...  in your .env file.

Safety features:
  * the free plan allows 200 requests a month; this script stops at MONTHLY_CAP (190)
  * it remembers where it stopped, so every run searches something new
  * every raw response is saved in data/raw_jsearch/ so nothing is paid for twice
Never share your .env file or put it on GitHub."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import requests

import collect_jooble as cj
from skills import (CITY_ALIASES, city_from_text, classify_experience, clean_text,
                    detect_work_mode, extract_skills, min_years_required, role_family)

API_URL = "https://api.openwebninja.com/jsearch/search"
STATE_PATH = cj.DATA / "jsearch_state.json"
RAW_DIR = cj.DATA / "raw_jsearch"
MONTHLY_CAP = 190          # the free plan gives 200; keep 10 spare
MAX_PAGES = 2              # page 1 of every search first, then page 2
PAUSE_SECONDS = 1.0

QUERIES = [
    "data analyst in India", "junior data analyst fresher in India", "business analyst in India",
    "power bi developer in India", "sql data analyst in India", "senior data analyst in India",
    "bi analyst reporting in India", "remote data analyst in India", "hybrid data analyst in India",
    "data analyst internship in India",
    "data analyst in Bengaluru", "data analyst in Hyderabad", "data analyst in Pune",
    "data analyst in Mumbai", "data analyst in Delhi NCR", "data analyst in Chennai",
    "data analyst in Gurugram", "data analyst in Noida", "data analyst in Kolkata",
    "data analyst in Ahmedabad",
]

EXTRA_COLUMNS = {"state": "TEXT", "publisher": "TEXT", "exp_min_years": "REAL",
                 "latitude": "REAL", "longitude": "REAL"}


def ensure_schema(conn):
    """Shared tables from the Jooble collector, plus the extra columns JSearch fills in."""
    cj.ensure_schema(conn)
    have = {r[1] for r in conn.execute("PRAGMA table_info(live_jobs)")}
    for col, typ in EXTRA_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE live_jobs ADD COLUMN {col} {typ}")
    conn.commit()


def this_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def load_state():
    state = {"month": this_month(), "used": 1, "next": 0}     # 1 = your first test request
    if STATE_PATH.exists():
        old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state.update({k: old[k] for k in ("month", "used", "next") if k in old})
    if state["month"] != this_month():                           # new month: fresh allowance
        state.update({"month": this_month(), "used": 0})
    return state


def save_state(state):
    cj.DATA.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def build_tasks():
    return [(q, page) for page in range(1, MAX_PAGES + 1) for q in QUERIES]


def fetch_page(key, query, page):
    r = requests.get(API_URL, headers={"x-api-key": key},
                     params={"query": query, "country": "in", "page": str(page), "num_pages": "1"},
                     timeout=60)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


_OTHERS = re.compile(r"\(\+\d+ others?\)", re.I)
_TITLE_TAIL = re.compile(r"\s*\|\s*[^|]*,\s*India\s*$", re.I)


def is_india(j):
    country = (j.get("job_country") or "").upper()
    if country:
        return country == "IN"
    loc = (j.get("job_location") or "").lower()
    return "india" in loc or any(p.strip() in CITY_ALIASES for p in loc.split(","))


def salary_text(j):
    if j.get("job_salary_string"):
        return j["job_salary_string"]
    lo, hi = j.get("job_min_salary"), j.get("job_max_salary")
    if lo or hi:
        return f"{lo or '?'} - {hi or '?'} per {j.get('job_salary_period') or 'period'}"
    return None


def parse_job(j, found_by, now_iso):
    title = _TITLE_TAIL.sub("", clean_text(j.get("job_title") or ""))
    desc = clean_text(j.get("job_description") or "")
    loc_raw = j.get("job_location")
    loc_clean = _OTHERS.sub("", loc_raw or "").strip()
    city = city_from_text(j.get("job_city") or "") if j.get("job_city") else city_from_text(loc_clean)

    if j.get("job_is_remote"):
        mode = "Remote"
    else:
        mode = detect_work_mode(f"{title}. {loc_clean}")
        if mode == "Not stated":
            mode = detect_work_mode(desc)

    raw_id = j.get("job_uid") or hashlib.md5(
        ((j.get("job_id") or "") + (j.get("job_apply_link") or title)).encode("utf-8")).hexdigest()
    row = {
        "job_id": f"jsearch-{raw_id}", "source": "jsearch", "title": title,
        "company": j.get("employer_name"), "city": city, "location_raw": loc_raw,
        "job_type": j.get("job_employment_type"), "work_mode": mode,
        "experience_level": classify_experience(title, desc),
        "role_family": role_family(title), "salary_text": salary_text(j),
        "updated_at": j.get("job_posted_at_datetime_utc"),
        "first_seen": now_iso, "last_seen": now_iso, "snippet": desc[:1500],
        "url": j.get("job_apply_link"), "found_by": found_by,
        "state": j.get("job_state"), "publisher": j.get("job_publisher"),
        "exp_min_years": min_years_required(desc),
        "latitude": j.get("job_latitude"), "longitude": j.get("job_longitude"),
    }
    return row, extract_skills(f"{title}. {desc}")


def run(key, max_requests, conn, state, pause=PAUSE_SECONDS):
    tasks = build_tasks()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    used_now = seen = new = 0
    note = "ok"
    while used_now < max_requests:
        if state["used"] >= MONTHLY_CAP:
            note = f"stopped: monthly cap {MONTHLY_CAP} reached"
            break
        if state["next"] >= len(tasks):
            state["next"] = 0
        q, page = tasks[state["next"]]
        state["next"] += 1
        status, data = fetch_page(key, q, page)
        state["used"] += 1
        used_now += 1
        if status != 200:
            note = f"stopped: HTTP {status}"
            save_state(state)
            break
        RAW_DIR.joinpath(now_iso[:10]).mkdir(parents=True, exist_ok=True)
        fname = re.sub(r"[^a-z0-9]+", "_", f"{q}_p{page}_{now_iso[11:19]}".lower()) + ".json"
        RAW_DIR.joinpath(now_iso[:10], fname).write_text(json.dumps(data), encoding="utf-8")
        for j in data.get("data") or []:
            if not is_india(j):
                continue
            row, skills = parse_job(j, f"{q} (p{page})", now_iso)
            seen += 1
            if cj.upsert(conn, row, skills):
                new += 1
        conn.commit()
        save_state(state)
        time.sleep(pause)
    conn.execute("INSERT INTO collect_runs (started_at, requests_used, jobs_seen, jobs_new, note) "
                 "VALUES (?, ?, ?, ?, ?)", (now_iso, used_now, seen, new, "jsearch: " + note))
    conn.commit()
    return used_now, seen, new, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=6)
    args = ap.parse_args()
    cj.load_env()
    key = os.environ.get("JSEARCH_KEY")
    if not key:
        raise SystemExit("Add JSEARCH_KEY=... to your .env file first.")
    cj.DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(cj.DB_PATH)
    ensure_schema(conn)
    state = load_state()
    used, seen, new, note = run(key, args.max_requests, conn, state)
    total = conn.execute("SELECT COUNT(*) FROM live_jobs WHERE source='jsearch'").fetchone()[0]
    print(f"Requests used this run: {used}   |   this month: {state['used']} of {MONTHLY_CAP} allowed")
    print(f"JSearch jobs seen: {seen}, new: {new}, total JSearch jobs in database: {total}  [{note}]")
    for label, col in (("Role family", "role_family"), ("Work mode", "work_mode"),
                       ("Experience", "experience_level"), ("Top cities", "city"),
                       ("Sources", "publisher")):
        rows = conn.execute(f"SELECT {col}, COUNT(*) FROM live_jobs WHERE source='jsearch' "
                            f"GROUP BY {col} ORDER BY 2 DESC LIMIT 7").fetchall()
        print(f"{label}:", ", ".join(f"{a} {b}" for a, b in rows))
    conn.close()


if __name__ == "__main__":
    main()
