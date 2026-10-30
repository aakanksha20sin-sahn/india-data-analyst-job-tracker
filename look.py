"""Summarises the 2023 India data. Run from your Job Tracker folder:   python look.py
It writes report.txt and india_sample.csv in the same folder. Nothing is sent anywhere."""
import ast
from collections import Counter
from pathlib import Path

import pandas as pd

for p in ("raw data/data_jobs.parquet", "data_jobs.parquet"):
    if Path(p).exists():
        PARQUET = p
        break
else:
    raise SystemExit("Cannot find data_jobs.parquet (looked in 'raw data' and this folder).")

out = []
def say(*a):
    line = " ".join(str(x) for x in a)
    out.append(line)
    print(line)

df = pd.read_parquet(PARQUET)
ind = df[df["job_country"] == "India"].copy()
say("India rows:", len(ind), "of", len(df))
say("Columns:", ", ".join(f"{c}({t})" for c, t in ind.dtypes.astype(str).items()))
say("\nRole groups (job_title_short):\n" + ind["job_title_short"].value_counts().to_string())
dates = pd.to_datetime(ind["job_posted_date"], errors="coerce")
say("\nPosted dates:", dates.min(), "to", dates.max())
say("Rows per month:\n" + dates.dt.to_period("M").value_counts().sort_index().to_string())
say("\nWork from home flag:\n" + ind["job_work_from_home"].value_counts(dropna=False).to_string())
say("\nSchedule type:\n" + ind["job_schedule_type"].value_counts(dropna=False).head(8).to_string())
say("\nTop sites (job_via):\n" + ind["job_via"].value_counts().head(10).to_string())
say("\nTop locations:\n" + ind["job_location"].value_counts().head(15).to_string())
say("\nTop companies:\n" + ind["company_name"].value_counts().head(10).to_string())
say("\nRows with skills listed:", int(ind["job_skills"].notna().sum()))
say("Rows with yearly salary:", int(ind["salary_year_avg"].notna().sum()))
if ind["salary_year_avg"].notna().any():
    say(ind["salary_year_avg"].describe().round(0).to_string())
    say("salary_rate values:", ind["salary_rate"].value_counts(dropna=False).to_dict())

counts = Counter()
for v in ind["job_skills"].dropna():
    try:
        items = ast.literal_eval(v) if isinstance(v, str) else list(v)
    except Exception:
        continue
    counts.update(str(i).lower() for i in items)
say("\nTop skills:", ", ".join(f"{k} {n}" for k, n in counts.most_common(20)))

Path("report.txt").write_text("\n".join(out), encoding="utf-8")
ind.sample(min(2000, len(ind)), random_state=1).to_csv("india_sample.csv", index=False)
print("\nSaved report.txt and india_sample.csv")
