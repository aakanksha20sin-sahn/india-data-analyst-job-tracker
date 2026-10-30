"""Load the 2023 India analyst-type jobs (Hugging Face data_jobs) into your database.

Run from your "Job Tracker" folder:
    python load_archive.py

It creates two tables  archive_jobs  and  archive_job_skills  with the SAME columns as the live
tables, and a view  all_jobs  (live + 2023 together, with a 'period' column).
Safe to run again: it rebuilds the archive tables from scratch each time."""
import ast
import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

import collect_jsearch as cs
from skills import (city_from_text, classify_experience, clean_text, detect_work_mode,
                    extract_skills, role_family)

DB_PATH = cs.cj.DB_PATH
ANALYST_GROUPS = {"Data Analyst", "Senior Data Analyst", "Business Analyst"}
KEEP_FROM_TITLE = {"Data Analyst", "Business Analyst", "BI / Reporting"}
GROUP_TO_FAMILY = {"Data Analyst": "Data Analyst", "Senior Data Analyst": "Data Analyst",
                   "Business Analyst": "Business Analyst"}

# the dataset's lower-case skill names -> the names used everywhere else in this project
SKILL_MAP = {
    "sql": "SQL", "mysql": "MySQL", "postgresql": "PostgreSQL", "excel": "Excel", "python": "Python",
    "r": "R", "power bi": "Power BI", "powerbi": "Power BI", "tableau": "Tableau",
    "looker": "Looker Studio", "qlik": "Qlik", "pandas": "Pandas", "numpy": "NumPy",
    "aws": "AWS", "redshift": "AWS", "azure": "Azure", "gcp": "Google Cloud", "bigquery": "Google Cloud",
    "snowflake": "Snowflake", "spark": "Spark", "pyspark": "Spark", "databricks": "Spark",
    "sheets": "Google Sheets", "vba": "VBA / Macros", "sas": "SAS", "spss": "SPSS",
    "git": "Git", "github": "Git",
}


INDIAN_STATES = {s.lower() for s in (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh",
    "Chandigarh", "Puducherry")}


def city_and_state(location):
    """('Bengaluru', 'Karnataka') for a full address; a state-only location gives ('Not stated', state)."""
    parts = [p.strip() for p in str(location or "").split(",") if p.strip()]
    parts = [p for p in parts if p.lower() != "india"]
    if not parts:
        return "Not stated", None
    if parts[0].lower() in INDIAN_STATES and parts[0].lower() != "delhi":
        return "Not stated", parts[0]
    return city_from_text(parts[0]), (parts[1] if len(parts) > 1 else None)


def skills_from(value):
    if value is None or (isinstance(value, float) and value != value):
        return []
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except Exception:
            value = [value]
    try:
        names = [str(v).strip().lower() for v in value]
    except TypeError:
        return []
    found = {SKILL_MAP[n] for n in names if n in SKILL_MAP}
    found |= set(extract_skills(", ".join(names)))
    return sorted(found)


def to_row(r):
    title = clean_text(str(r["job_title"] or ""))
    group = r["job_title_short"]
    family = role_family(title)
    if family in ("Not analytics", "Other analyst"):
        family = GROUP_TO_FAMILY.get(group, family)
    remote = bool(r["job_work_from_home"])
    mode = "Remote" if remote else detect_work_mode(title)
    exp = classify_experience(title, "")
    if exp == "Not stated" and str(group).startswith("Senior"):
        exp = "Senior"
    loc = r["job_location"] or ""
    city, state = city_and_state(loc)
    posted = pd.to_datetime(r["job_posted_date"], errors="coerce")
    posted_iso = None if pd.isna(posted) else posted.isoformat(timespec="seconds")
    key = "|".join(str(x) for x in (title, r["company_name"], loc, posted_iso, r["job_via"]))
    row = {
        "job_id": "hf2023-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:16],
        "source": "huggingface-2023", "title": title or "(no title)", "company": r["company_name"],
        "city": "Remote (anywhere)" if remote and str(loc).lower() == "anywhere" else city,
        "location_raw": loc, "job_type": r["job_schedule_type"], "work_mode": mode,
        "experience_level": exp, "role_family": family, "salary_text": None,
        "updated_at": posted_iso, "first_seen": posted_iso or "2023", "last_seen": posted_iso or "2023",
        "snippet": None, "url": None, "found_by": group,
        "state": state,
        "publisher": str(r["job_via"] or "").replace("via ", "").strip() or None,
        "exp_min_years": None, "latitude": None, "longitude": None,
    }
    return row, skills_from(r["job_skills"])


def load(parquet_path, conn):
    cs.ensure_schema(conn)
    conn.execute("DROP TABLE IF EXISTS archive_jobs")
    conn.execute("DROP TABLE IF EXISTS archive_job_skills")
    conn.execute("CREATE TABLE archive_jobs AS SELECT * FROM live_jobs WHERE 0")
    conn.execute("CREATE UNIQUE INDEX ux_archive_job ON archive_jobs(job_id)")
    conn.execute("CREATE TABLE archive_job_skills (job_id TEXT NOT NULL, skill TEXT NOT NULL, "
                 "PRIMARY KEY (job_id, skill))")

    df = pd.read_parquet(parquet_path)
    df = df[df["job_country"] == "India"]
    family_from_title = df["job_title"].fillna("").map(lambda t: role_family(clean_text(t)))
    keep = df["job_title_short"].isin(ANALYST_GROUPS) | family_from_title.isin(KEEP_FROM_TITLE)
    df = df[keep & ~family_from_title.isin({"Data Scientist", "Data Engineer"})]

    cols = [c[1] for c in conn.execute("PRAGMA table_info(live_jobs)")]
    inserted = 0
    for _, r in df.iterrows():
        row, skills = to_row(r)
        cur = conn.execute(f"INSERT OR IGNORE INTO archive_jobs ({','.join(cols)}) "
                           f"VALUES ({','.join('?' for _ in cols)})", [row.get(c) for c in cols])
        if cur.rowcount:
            inserted += 1
            conn.executemany("INSERT OR IGNORE INTO archive_job_skills VALUES (?, ?)",
                             [(row["job_id"], s) for s in skills])
    conn.execute("DROP VIEW IF EXISTS all_jobs")
    col_list = ",".join(cols)
    conn.execute(f"CREATE VIEW all_jobs AS "
                 f"SELECT 'live' AS period, {col_list} FROM live_jobs "
                 f"UNION ALL SELECT '2023' AS period, {col_list} FROM archive_jobs")
    conn.execute("DROP VIEW IF EXISTS all_job_skills")
    conn.execute("CREATE VIEW all_job_skills AS SELECT job_id, skill FROM live_job_skills "
                 "UNION ALL SELECT job_id, skill FROM archive_job_skills")
    conn.commit()
    return len(df), inserted


def main():
    path = next((p for p in ("raw data/data_jobs.parquet", "data_jobs.parquet") if Path(p).exists()), None)
    if not path:
        raise SystemExit("Cannot find data_jobs.parquet (looked in 'raw data' and this folder).")
    conn = sqlite3.connect(DB_PATH)
    candidates, inserted = load(path, conn)
    print(f"India analyst-type rows found: {candidates}   loaded (duplicates removed): {inserted}")
    q = lambda sql: conn.execute(sql).fetchall()
    fmt = lambda rows: ", ".join(f"{a} {b}" for a, b in rows)
    print("Role family:", fmt(q("SELECT role_family, COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 2 DESC")))
    print("Work mode:", fmt(q("SELECT work_mode, COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 2 DESC")))
    print("Experience:", fmt(q("SELECT experience_level, COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 2 DESC")))
    print("Top cities:", fmt(q("SELECT city, COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 2 DESC LIMIT 8")))
    print("Top companies:", fmt(q("SELECT company, COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 2 DESC LIMIT 6")))
    print("Top companies in Hyderabad:", fmt(q("SELECT company, COUNT(*) FROM archive_jobs WHERE city='Hyderabad' GROUP BY 1 ORDER BY 2 DESC LIMIT 5")))
    print("Top sites:", fmt(q("SELECT publisher, COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 2 DESC LIMIT 6")))
    print("Top skills:", fmt(q("SELECT skill, COUNT(*) FROM archive_job_skills GROUP BY 1 ORDER BY 2 DESC LIMIT 10")))
    print("Months:", fmt(q("SELECT substr(updated_at,1,7), COUNT(*) FROM archive_jobs GROUP BY 1 ORDER BY 1")))
    print("All jobs (view):", fmt(q("SELECT period, COUNT(*) FROM all_jobs GROUP BY 1")))
    conn.close()


if __name__ == "__main__":
    main()
