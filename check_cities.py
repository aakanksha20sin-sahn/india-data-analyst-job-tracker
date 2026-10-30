import sqlite3
c = sqlite3.connect("data/jobs.db")
q = "SELECT city, COUNT(*) FROM jobs_clean WHERE period='live' GROUP BY city ORDER BY 2 DESC"
for r in c.execute(q).fetchall():
    print(r)
print("--- raw locations ---")
q2 = "SELECT location_raw, COUNT(*) FROM jobs_clean WHERE period='live' GROUP BY location_raw ORDER BY 2 DESC LIMIT 25"
for r in c.execute(q2).fetchall():
    print(r)