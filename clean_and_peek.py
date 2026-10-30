import sqlite3

conn = sqlite3.connect("data/jobs.db")
q = lambda sql: conn.execute(sql).fetchall()

# remove the 2 old non-India rows
conn.execute("DELETE FROM live_job_skills WHERE job_id IN (SELECT job_id FROM live_jobs WHERE COALESCE(location_raw,'') NOT LIKE '%India%')")
conn.execute("DELETE FROM live_jobs WHERE COALESCE(location_raw,'') NOT LIKE '%India%'")
conn.commit()

print("Jobs:", q("SELECT COUNT(*) FROM live_jobs")[0][0])
print("Dates:", q("SELECT MIN(updated_at), MAX(updated_at) FROM live_jobs"))
print("\nTop companies:")
for r in q("SELECT company, COUNT(*) FROM live_jobs GROUP BY company ORDER BY 2 DESC LIMIT 10"):
    print(" ", r)
print("\nSkills (% of postings, from short snippets):")
for r in q("SELECT skill, ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM live_jobs),1) FROM live_job_skills GROUP BY skill ORDER BY 2 DESC LIMIT 10"):
    print(" ", r)
print("\nSample of rows marked Senior:")
for r in q("SELECT title, substr(snippet,1,110) FROM live_jobs WHERE experience_level='Senior' ORDER BY RANDOM() LIMIT 8"):
    print(" -", r)