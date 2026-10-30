"""Collect live India analyst postings from Jooble into a local SQLite database.

Run from your "Job Tracker" folder (where the .env file is):
    python collect_jooble.py                 # uses up to 10 requests
    python collect_jooble.py --max-requests 25

Safety features:
  * stops at --max-requests per run, and never goes past TOTAL_CAP requests overall
    (the key's limit is 500; Jooble did not say if that is per month or in total)
  * remembers where it stopped, so each run continues with new searches
  * saves every raw response under data/raw_jooble/ so nothing is paid for twice
Never share your .env file or put it on GitHub."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from skills import (CITY_ALIASES, classify_experience, city_from_text, clean_text,
                    detect_work_mode, extract_skills, role_family)

DATA = Path("data")
DB_PATH = DATA / "jobs.db"
STATE_PATH = DATA / "jooble_state.json"
RAW_DIR = DATA / "raw_jooble"

QUERIES = ["data analyst", "business analyst", "power bi analyst", "sql analyst",
           "junior data analyst", "senior data analyst", "fresher data analyst", "bi developer",
           "data analytics", "reporting analyst", "mis analyst", "tableau analyst"]
# Your test showed city searches (Pune, Mumbai, ...) return 0 jobs on Jooble,
# and 'Delhi' returned a US result. So we search the whole country only.
LOCATIONS = ["India"]
MAX_PAGES = 5           # totalCount was 150 for "data analyst" = 5 pages of 30
FULL_PAGE = 30          # one call returned 30 jobs in your test
TOTAL_CAP = 450         # keep 50 of the 500 requests spare
PAUSE_SECONDS = 1.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_jobs (
    job_id           TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    title            TEXT NOT NULL,
    company          TEXT,
    city             TEXT,
    location_raw     TEXT,
    job_type         TEXT,
    work_mode        TEXT,
    experience_level TEXT,
    role_family      TEXT,
    salary_text      TEXT,
    updated_at       TEXT,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    snippet          TEXT,
    url              TEXT,
    found_by         TEXT
);
CREATE TABLE IF NOT EXISTS live_job_skills (
    job_id TEXT NOT NULL,
    skill  TEXT NOT NULL,
    PRIMARY KEY (job_id, skill)
);
CREATE TABLE IF NOT EXISTS collect_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    requests_used INTEGER,
    jobs_seen     INTEGER,
    jobs_new      INTEGER,
    note          TEXT
);
"""


def load_env():
    for p in (Path(".env"), Path("../.env")):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


def load_state():
    state = {"used": 0, "next": 0, "exhausted": [], "v": 2}
    if STATE_PATH.exists():
        old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state["used"] = old.get("used", 0)            # always keep the request count
        if old.get("v") == 2:                         # same task list: keep position too
            state["next"] = old.get("next", 0)
            state["exhausted"] = old.get("exhausted", [])
    return state


def save_state(state):
    DATA.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def build_tasks():
    """Breadth first: page 1 of every search, then page 2, then page 3."""
    return [(q, loc, page) for page in range(1, MAX_PAGES + 1)
            for q in QUERIES for loc in LOCATIONS]


def fetch_page(key, query, location, page):
    resp = requests.post(f"https://jooble.org/api/{key}",
                         json={"keywords": query, "location": location, "page": page},
                         timeout=30)
    return resp.status_code, (resp.json() if resp.status_code == 200 else {})


def parse_job(j, found_by, now_iso):
    title = clean_text(j.get("title") or "")
    snippet = clean_text(j.get("snippet") or "")
    raw_id = j.get("id")
    if raw_id is None:
        raw_id = hashlib.md5((j.get("link") or title).encode("utf-8")).hexdigest()
    text = f"{title}. {snippet}"
    row = {
        "job_id": f"jooble-{raw_id}", "source": "jooble", "title": title,
        "company": j.get("company"), "city": city_from_text(j.get("location")),
        "location_raw": j.get("location"), "job_type": j.get("type"),
        "work_mode": detect_work_mode(f"{text} {j.get('location') or ''}"),
        "experience_level": classify_experience(title, snippet),
        "role_family": role_family(title),
        "salary_text": j.get("salary") or None, "updated_at": j.get("updated"),
        "first_seen": now_iso, "last_seen": now_iso, "snippet": snippet,
        "url": j.get("link"), "found_by": found_by,
    }
    return row, extract_skills(text)


def upsert(conn, row, skills):
    if conn.execute("SELECT 1 FROM live_jobs WHERE job_id = ?", (row["job_id"],)).fetchone():
        conn.execute("UPDATE live_jobs SET last_seen = ? WHERE job_id = ?",
                     (row["last_seen"], row["job_id"]))
        return False
    cols = list(row.keys())
    conn.execute(f"INSERT INTO live_jobs ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                 [row[c] for c in cols])
    conn.executemany("INSERT OR IGNORE INTO live_job_skills (job_id, skill) VALUES (?, ?)",
                     [(row["job_id"], s) for s in skills])
    return True


def is_india(j):
    """Keep a job only if its location says India or names a known Indian city."""
    loc = (j.get("location") or "").strip()
    if not loc:
        return False
    if "india" in loc.lower():
        return True
    return any(p.strip().lower() in CITY_ALIASES for p in loc.split(","))


def run(key, max_requests, conn, state, pause=PAUSE_SECONDS):
    tasks = build_tasks()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    used_now = seen = new = 0
    note = "ok"
    guard = len(tasks) * 2
    while used_now < max_requests and guard > 0:
        guard -= 1
        if state["used"] >= TOTAL_CAP:
            note = f"stopped: total cap {TOTAL_CAP} reached"
            break
        if state["next"] >= len(tasks):
            state["next"], state["exhausted"] = 0, []
        q, loc, page = tasks[state["next"]]
        state["next"] += 1
        combo = f"{q}|{loc}"
        if combo in state["exhausted"]:
            continue
        status, data = fetch_page(key, q, loc, page)
        state["used"] += 1
        used_now += 1
        if status != 200:
            note = f"stopped: HTTP {status}"
            save_state(state)
            break
        RAW_DIR.joinpath(now_iso[:10]).mkdir(parents=True, exist_ok=True)
        fname = re.sub(r"[^a-z0-9]+", "_", f"{q}_{loc}_p{page}".lower()) + ".json"
        RAW_DIR.joinpath(now_iso[:10], fname).write_text(json.dumps(data), encoding="utf-8")
        jobs = data.get("jobs") or []
        page_new = 0
        for j in jobs:
            if not is_india(j):
                continue
            row, skills = parse_job(j, f"{q} / {loc}", now_iso)
            seen += 1
            if upsert(conn, row, skills):
                new += 1
                page_new += 1
        conn.commit()
        if len(jobs) < FULL_PAGE or (page > 1 and page_new == 0):
            state["exhausted"].append(combo)   # no point asking for later pages
        save_state(state)
        time.sleep(pause)
    conn.execute("INSERT INTO collect_runs (started_at, requests_used, jobs_seen, jobs_new, note) "
                 "VALUES (?, ?, ?, ?, ?)", (now_iso, used_now, seen, new, note))
    conn.commit()
    return used_now, seen, new, note


def ensure_schema(conn):
    """Create tables and upgrade an older database in place (safe to run every time).
    Re-cleans the text and re-labels older rows. Returns how many rows were upgraded."""
    conn.executescript(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(live_jobs)")]
    if "role_family" not in cols:
        conn.execute("ALTER TABLE live_jobs ADD COLUMN role_family TEXT")
    rows = conn.execute(
        "SELECT job_id, title, snippet, location_raw FROM live_jobs WHERE role_family IS NULL").fetchall()
    for job_id, title, snippet, loc in rows:
        t, s = clean_text(title), clean_text(snippet)
        conn.execute(
            "UPDATE live_jobs SET title=?, snippet=?, experience_level=?, work_mode=?, role_family=? "
            "WHERE job_id=?",
            (t, s, classify_experience(t, s), detect_work_mode(f"{t}. {s} {loc or ''}"),
             role_family(t), job_id))
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=10)
    args = ap.parse_args()
    load_env()
    key = os.environ.get("JOOBLE_KEY")
    if not key:
        raise SystemExit("Add JOOBLE_KEY=... to your .env file first.")
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    fixed = ensure_schema(conn)
    if fixed:
        print(f"Cleaned and re-labelled {fixed} older rows.")
    state = load_state()
    used, seen, new, note = run(key, args.max_requests, conn, state)
    total = conn.execute("SELECT COUNT(*) FROM live_jobs").fetchone()[0]
    print(f"Requests used this run: {used} (total so far: {state['used']} of {TOTAL_CAP} allowed)")
    print(f"Jobs seen: {seen}, new: {new}, total in database: {total}  [{note}]")
    n_an = conn.execute("SELECT COUNT(*) FROM live_jobs WHERE role_family != 'Not analytics'").fetchone()[0]
    print(f"Analytics-type roles: {n_an} of {total}")
    only = "WHERE role_family != 'Not analytics'"
    for label, col, where in (("Role family", "role_family", ""),
                              ("Work mode (analytics roles)", "work_mode", only),
                              ("Experience (analytics roles)", "experience_level", only)):
        rows = conn.execute(
            f"SELECT {col}, COUNT(*) FROM live_jobs {where} GROUP BY {col} ORDER BY 2 DESC LIMIT 7").fetchall()
        print(f"{label}:", ", ".join(f"{a} {b}" for a, b in rows))
    conn.close()


if __name__ == "__main__":
    main()
