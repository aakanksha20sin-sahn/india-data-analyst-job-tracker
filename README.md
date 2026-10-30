# India Data Analyst Job Market Tracker

A live dashboard of data-analytics job postings in India, updated automatically every day.

**Live dashboard:** https://india-data-analyst-job-tracker-ef2ufrju4qkn39ktvivfva.streamlit.app

![Overview](screenshots/overview.png)

## What it does
- Collects data-analyst, business-analyst and BI/reporting job postings in India every day (free API, no scraping).
- Cleans and de-duplicates them, so the dashboard counts **unique roles**, not repeated postings.
- Compares today's market (live) with a 2023 archive: role mix, cities, skills, remote share.
- Lists fresher / entry-level roles with direct Apply links.

## Dashboard tabs
| Tab | What you see |
|---|---|
| Overview | Unique roles, postings, companies, remote/hybrid share, role mix, top hiring companies |
| Cities | Map and ranking of cities (Bengaluru, Hyderabad, Pune, Gurugram, Noida, Mumbai and more) |
| Skills | Share of roles asking for SQL, Excel, Python, Power BI, Tableau and others |
| Work mode | Remote, hybrid and on-site roles, by city |
| Experience & freshers | Entry, mid and senior roles, skills for freshers, list of fresher jobs |
| Then vs Now | 2023 archive compared with live data |
| Jobs | Newest roles with an Apply link |

## Findings
- **Raw counts overstate demand.** In the 2023 archive, 9,289 postings collapse into 7,973 unique roles (about 14% fewer). In Hyderabad, Wells Fargo shows 130 postings but only 35 unique roles; S&P Global shows 64 postings but 20 unique roles.
- **Work mode is rarely stated.** Only about a quarter of live roles say whether they are remote, hybrid or on-site, so the remote share is shown with a warning, never guessed.
- **Core skills in the 2023 archive:** SQL, Excel, Python, Tableau and Power BI lead the list.
- At the time of writing, the live data holds about 500 unique roles (519 postings) and grows every day.

## How it works
```
JSearch API  --(GitHub Actions, daily 7:00 AM IST)-->  SQLite (jobs.db)
   2023 archive (Hugging Face) -----------------------^
                                 build_clean.py (clean + de-duplicate)
                                          |
                                   Streamlit dashboard
```
- `collect_jsearch.py` collects new postings (stays under the free 200 requests a month).
- `build_clean.py` keeps analytics roles only, removes non-India look-alikes, merges repeated postings (same title, company and city) and fills a missing city only when the text clearly names one.
- `load_archive.py` loads the 2023 India analyst roles.
- `app.py` is the Streamlit dashboard, with a live India-time clock.
- `.github/workflows/daily_update.yml` runs the daily update automatically.

## Honesty rules
- Missing information is shown as **Not stated**. Nothing is guessed.
- Salary is not a headline, because almost no posting states it.
- 2023 and live data are not directly comparable on work mode and experience (2023 comes from job titles only), and the dashboard says so.
- Only free sources; no scraping of Naukri, LinkedIn or Indeed.

## Data sources and credits
- Live postings: [JSearch API](https://www.openwebninja.com/) by OpenWeb Ninja (free plan). Each posting links to its original site.
- 2023 archive: [lukebarousse/data_jobs](https://huggingface.co/datasets/lukebarousse/data_jobs) on Hugging Face (Apache-2.0).
- Some early live data from the Jooble API.

## Run it on your own computer
```
pip install -r requirements.txt
streamlit run app.py
```
To collect new jobs you need your own JSearch key in a `.env` file: `JSEARCH_KEY=your_key`.

## Tech
Python, pandas, SQLite, Plotly, Streamlit, GitHub Actions.

## Author
Aakanksha Singh, final-year Electronics & Communication Engineering student, UIET, Panjab University.
