"""Build the clean tables the dashboard reads.   Run from your "Job Tracker" folder:
    python build_clean.py

Makes two tables in data/jobs.db (rebuilt from scratch every run, safe to repeat):
  jobs_clean         one row per UNIQUE role (postings counted in repost_count)
  jobs_clean_skills  skills of those roles (job_id, skill)
Rules:
  * analytics roles only (role_family != 'Not analytics')
  * drops obvious non-India rows (salary in EUR, Baltic cities/countries in the text)
  * unique role = same period + same title + same company + same city
    (period = 'live' or '2023'; Jooble and JSearch copies of one job merge)
  * company 'Confidential' / empty is NEVER merged (we cannot tell them apart)"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

from skills import CITY_ALIASES, city_from_text

DB_PATH = Path("data") / "jobs.db"
SOURCE_RANK = {"jsearch": 0, "jooble": 1, "huggingface-2023": 2}
NO_MERGE_COMPANIES = {"", "confidential", "unknown", "not stated", "n/a", "none"}
_FOREIGN = re.compile(r"\b(vilnius|riga|tallinn|lithuania|latvia|estonia|kaunas)\b", re.I)
_EUR = re.compile(r"\beur\b|€", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(text):
    return _NON_ALNUM.sub(" ", str(text or "").lower()).strip()


def is_foreign(row):
    if _EUR.search(str(row["salary_text"] or "")):
        return True
    return bool(_FOREIGN.search(f"{row['location_raw'] or ''} {str(row['snippet'] or '')[:1500]}"))


_CITY_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in CITY_ALIASES), key=len, reverse=True)) + r")\b", re.I)
_STATES = {"andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat",
           "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala", "keralam", "madhya pradesh",
           "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "punjab",
           "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand",
           "west bengal", "jammu and kashmir", "ladakh", "puducherry", "datta"}   # 'datta' = wrong tag seen in data
_BLANK_CITY = {"", "not stated", "none", "india", "delhi ncr"} | _STATES   # old merged label = ambiguous
_OTHERS = re.compile(r"\(\+\d+ others?\)", re.I)


def tidy_city(value):
    """'India (+2 others)' -> 'India'; 'Pune (+1 other)' -> 'Pune'."""
    return _OTHERS.sub("", str(value or "")).strip()


def cities_in(text):
    return {CITY_ALIASES[m.group(1).lower()] for m in _CITY_RX.finditer(str(text or ""))}


def fill_city(row):
    """Only when the city is missing: use a city NAMED in the title, else the one
    city named in the description. Two or more different cities = left 'Not stated'."""
    if str(row["city"] or "").strip() == "Remote (anywhere)":
        return row["city"]
    first = city_from_text(tidy_city(row["location_raw"]))     # re-read the city with the current city list
    if first.lower() not in _BLANK_CITY and first.lower() != "anywhere":
        return first
    current = tidy_city(row["city"])
    if current.lower() not in _BLANK_CITY:
        return current
    found = cities_in(row["title"])
    if len(found) == 1:
        return next(iter(found))
    if not found:
        found = cities_in(str(row["snippet"] or "")[:1500])
        if len(found) == 1:
            return next(iter(found))
    return "Not stated"


def dedupe_key(row):
    company = norm(row["company"])
    if company in NO_MERGE_COMPANIES:
        return f"{row['period']}|{row['job_id']}"          # unique, never merged
    return f"{row['period']}|{norm(row['title'])}|{company}|{norm(row['city'])}"


def build(conn):
    has_archive = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='archive_jobs'").fetchone() is not None
    sql = "SELECT 'live' AS period, * FROM live_jobs"
    sk = "SELECT job_id, skill FROM live_job_skills"
    if has_archive:
        sql += " UNION ALL SELECT '2023' AS period, * FROM archive_jobs"
        sk += " UNION ALL SELECT job_id, skill FROM archive_job_skills"
    df = pd.read_sql_query(sql, conn)
    skills = pd.read_sql_query(sk, conn)
    raw_total = len(df)

    df = df[df["role_family"] != "Not analytics"].copy()
    n_analytics = len(df)
    if len(df):
        df = df[~df.apply(is_foreign, axis=1)].copy()
    n_after_foreign = len(df)

    if len(df):
        df["city"] = df.apply(fill_city, axis=1)
    df["dedupe_key"] = df.apply(dedupe_key, axis=1)
    df["_rank"] = df["source"].map(SOURCE_RANK).fillna(9)
    df["_has_text"] = df["snippet"].notna().astype(int)
    df["_day"] = df["updated_at"].astype(str).str[:10]
    df = df.sort_values(["dedupe_key", "_has_text", "_rank", "_day"],
                        ascending=[True, False, True, False])
    grp = df.groupby("dedupe_key", sort=False)
    keep = grp.head(1).copy()
    extra = grp.agg(repost_count=("job_id", "count"),
                    first_posted=("_day", "min"), last_posted=("_day", "max"),
                    first_seen_all=("first_seen", "min"), last_seen_all=("last_seen", "max"),
                    sources=("source", lambda s: ", ".join(sorted(set(s))))).reset_index()
    keep = keep.drop(columns=["first_seen", "last_seen", "_rank", "_has_text", "_day"])
    keep = keep.merge(extra, on="dedupe_key").rename(
        columns={"first_seen_all": "first_seen", "last_seen_all": "last_seen"})

    rep = dict(zip(df["job_id"], df["dedupe_key"]))
    key_to_rep = dict(zip(keep["dedupe_key"], keep["job_id"]))
    skills = skills[skills["job_id"].isin(rep)].copy()
    skills["job_id"] = skills["job_id"].map(lambda j: key_to_rep[rep[j]])
    skills = skills.drop_duplicates()

    keep.to_sql("jobs_clean", conn, if_exists="replace", index=False)
    skills.to_sql("jobs_clean_skills", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_clean_period ON jobs_clean(period)")
    conn.commit()
    return {"raw": raw_total, "analytics": n_analytics, "after_foreign": n_after_foreign,
            "unique": len(keep)}


def report(conn, stats):
    q = lambda s: conn.execute(s).fetchall()
    print(f"All rows (live + 2023): {stats['raw']}")
    print(f"  analytics roles only: {stats['analytics']}")
    print(f"  after removing non-India look-alikes: {stats['after_foreign']}")
    print(f"  UNIQUE roles: {stats['unique']}")
    for period, postings, unique in q(
            "SELECT period, SUM(repost_count), COUNT(*) FROM jobs_clean GROUP BY period"):
        print(f"  [{period}] postings {postings} -> unique roles {unique}")
    print("Most reposted roles:")
    for r in q("SELECT title, company, city, repost_count FROM jobs_clean "
               "ORDER BY repost_count DESC LIMIT 5"):
        print("  ", r)
    print("Hyderabad 2023, top companies (postings, unique roles):")
    for r in q("SELECT company, SUM(repost_count), COUNT(*) FROM jobs_clean "
               "WHERE city='Hyderabad' AND period='2023' GROUP BY company ORDER BY 2 DESC LIMIT 5"):
        print("  ", r)


def main():
    if not DB_PATH.exists():
        raise SystemExit("Cannot find data/jobs.db - run this from the Job Tracker folder.")
    conn = sqlite3.connect(DB_PATH)
    report(conn, build(conn))
    conn.close()


if __name__ == "__main__":
    main()