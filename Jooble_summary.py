import json
from pathlib import Path

for f in sorted(Path("data/raw_jooble").rglob("*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    jobs = d.get("jobs") or []
    locs = sorted({(j.get("location") or "") for j in jobs})[:5]
    print(f"{f.name}: totalCount={d.get('totalCount')}, jobs={len(jobs)}, locations={locs}")