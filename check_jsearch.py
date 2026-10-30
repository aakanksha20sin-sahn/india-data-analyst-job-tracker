import json, os
from pathlib import Path
import requests

for p in (Path(".env"), Path("../.env")):
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
key = os.environ.get("JSEARCH_KEY")
if not key:
    raise SystemExit("Add a line  JSEARCH_KEY=your_key  to your .env file first.")

r = requests.get("https://api.openwebninja.com/jsearch/search",
                 headers={"x-api-key": key},
                 params={"query": "data analyst in India", "country": "in", "page": "1", "num_pages": "1"},
                 timeout=60)
print("HTTP status:", r.status_code)
try:
    data = r.json()
except Exception:
    print(r.text[:500]); raise SystemExit
Path("jsearch_sample.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
jobs = data.get("data") or []
print("Jobs returned in this ONE request:", len(jobs))
for j in jobs[:5]:
    print("-", j.get("job_title"), "|", j.get("employer_name"), "|", j.get("job_city"), "| remote:", j.get("job_is_remote"))
if not jobs:
    print(str(data)[:500])
print("Saved jsearch_sample.json - attach that file here.")