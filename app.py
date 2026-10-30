"""India Data Analyst Job Market Tracker - dashboard v1.
Run from the Job Tracker folder:   streamlit run app.py
Reads data/jobs.db (tables jobs_clean and jobs_clean_skills made by build_clean.py)."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

DB = Path("data") / "jobs.db"
PERIODS = {"Live (now)": "live", "Archive (2023)": "2023"}
CITY_LATLON = {
    "Bengaluru": (12.97, 77.59), "Hyderabad": (17.38, 78.48), "Mumbai": (19.08, 72.88),
    "Delhi": (28.61, 77.21), "Gurugram": (28.46, 77.03), "Noida": (28.54, 77.39),
    "Ghaziabad": (28.67, 77.45), "Faridabad": (28.41, 77.31), "Mohali": (30.70, 76.72), "Panchkula": (30.69, 76.85), "Pune": (18.52, 73.86), "Chennai": (13.08, 80.27),
    "Kolkata": (22.57, 88.36), "Ahmedabad": (23.02, 72.57), "Jaipur": (26.91, 75.79),
    "Lucknow": (26.85, 80.95), "Indore": (22.72, 75.86), "Kochi": (9.93, 76.27),
    "Chandigarh": (30.73, 76.78), "Thiruvananthapuram": (8.52, 76.94), "Bhopal": (23.26, 77.41),
    "Surat": (21.17, 72.83), "Nagpur": (21.15, 79.09), "Coimbatore": (11.02, 76.96),
    "Visakhapatnam": (17.69, 83.22), "Vadodara": (22.31, 73.18),
}
NOT_CITY = {"Not stated", "Remote (anywhere)"}

st.set_page_config(page_title="India Data Analyst Job Tracker", page_icon="📈", layout="wide")

# ---------- look and feel: teal + saffron, colour-blind friendly (change the colours here) ----------
# Colours alternate DARK and LIGHT so they can be told apart even without seeing hue.
PALETTE = ["#0B6E6E", "#A8DB9A", "#6B1F4A", "#F4B860", "#3D5A80", "#D9ECC8", "#E8871E"]
INK, GRID = "#2B2118", "#E6DCCB"
pio.templates["tracker"] = go.layout.Template(layout=dict(
    colorway=PALETTE, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Georgia, serif", color=INK), title=dict(font=dict(size=18, color=INK)),
    xaxis=dict(gridcolor=GRID, zerolinecolor=GRID), yaxis=dict(gridcolor=GRID, zerolinecolor=GRID)))
px.defaults.template = "tracker"
st.markdown(f"""<style>
.stApp {{ background: #FBF7F0; color: {INK}; }}
[data-testid="stSidebar"] {{ background: #F3EADB; }}
h1, h2, h3 {{ font-family: Georgia, 'Times New Roman', serif !important; color: #0B6E6E; }}
[data-testid="stMetricValue"] {{ color: #C8553D; font-family: Georgia, serif; }}
[data-testid="stMetric"] {{ background: #F3EADB; border-left: 5px solid #E8871E; padding: 10px 14px; border-radius: 6px; }}
[data-baseweb="select"] > div {{ background: #FFFFFF; border-radius: 10px; }}
.stTabs [aria-selected="true"] {{ color: #0B6E6E !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: #0B6E6E; }}
</style>""", unsafe_allow_html=True)


def show(fig, **kw):
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(automargin=True)
    st.plotly_chart(fig, theme=None, width="stretch")


@st.cache_data(show_spinner=False, ttl=3600)
def load(db_version):   # db_version changes whenever jobs.db changes, so new data always shows
    conn = sqlite3.connect(DB)
    jobs = pd.read_sql_query("SELECT * FROM jobs_clean", conn)
    skills = pd.read_sql_query("SELECT * FROM jobs_clean_skills", conn)
    conn.close()
    return jobs, skills


if not DB.exists():
    st.error("data/jobs.db not found. Run this from the Job Tracker folder.")
    st.stop()
try:
    jobs, skills = load(DB.stat().st_mtime)
except Exception:
    st.error("Table jobs_clean not found. Run:  python build_clean.py")
    st.stop()

# ---------- sidebar filters ----------
st.sidebar.title("Filters")
period_label = st.sidebar.radio("Data period", list(PERIODS), help="Live = collected now. Archive = 2023 postings.")
df = jobs[jobs["period"] == PERIODS[period_label]].copy()
_n = df["city"].value_counts()
_small = set(_n[_n < 3].index) - NOT_CITY - set(CITY_LATLON)   # big cities always keep their own name
df["city_group"] = df["city"].where(~df["city"].isin(_small), "Other cities")   # cities with under 3 roles


def pick(label, col):
    options = sorted(df[col].dropna().unique())
    chosen = st.sidebar.multiselect(label, options)
    return chosen


for label, col in (("City", "city_group"), ("Role family", "role_family"), ("Experience", "experience_level"),
                   ("Work mode", "work_mode"), ("Source site", "publisher")):
    chosen = pick(label, col)
    if chosen:
        df = df[df[col].isin(chosen)]
skill_options = sorted(skills["skill"].unique())
skill_pick = st.sidebar.multiselect("Skill (job must ask for all)", skill_options)
for s in skill_pick:
    df = df[df["job_id"].isin(skills.loc[skills["skill"] == s, "job_id"])]

# ---------- header ----------
st.title("India Data Analyst Job Market Tracker")
live = jobs[jobs["period"] == "live"]
last = live["last_seen"].max() if len(live) else None
IST = timezone(timedelta(hours=5, minutes=30))          # India time
STAMP = pd.to_datetime(last, utc=True).tz_convert(IST) if last else None
N_LIVE, N_OLD = len(live), int((jobs["period"] == "2023").sum())


def ago(delta):
    mins = int(delta.total_seconds() // 60)
    if mins < 2:
        return "just now"
    if mins < 60:
        return f"{mins} minutes ago"
    if mins < 48 * 60:
        return f"{mins // 60} hours ago"
    return f"{mins // 1440} days ago"


@st.fragment(run_every=60)
def live_clock():
    """Real clock: today's date and time now (India time); also the 'ago' text. Refreshes every minute."""
    now = datetime.now(IST)
    st.markdown(f"**Today:** {now:%A, %d %B %Y} &nbsp;|&nbsp; **Time now:** {now:%I:%M %p} IST")
    updated = f"{STAMP:%d %b %Y, %I:%M %p} IST ({ago(now - STAMP)})" if STAMP is not None else "no live data yet"
    st.caption(f"New jobs last collected: {updated}  |  Live unique roles: {N_LIVE}  |  "
               f"Archive roles (2023): {N_OLD}  |  Data is collected automatically every day.")


live_clock()

if df.empty:
    st.warning("No jobs match these filters. Remove a filter in the sidebar.")
    st.stop()

tab_over, tab_city, tab_skill, tab_work, tab_exp, tab_then, tab_jobs = st.tabs(
    ["Overview", "Cities", "Skills", "Work mode", "Experience & freshers", "Then vs Now", "Jobs"])

# ---------- overview ----------
with tab_over:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Unique roles", f"{len(df):,}")
    c2.metric("Postings (incl. reposts)", f"{int(df['repost_count'].sum()):,}")
    known_co = df[~df["company"].fillna("").str.lower().isin(["confidential", ""])]
    c3.metric("Companies", f"{known_co['company'].nunique():,}")
    stated = df[df["work_mode"] != "Not stated"]
    flex = stated["work_mode"].isin(["Remote", "Hybrid"]).mean() * 100 if len(stated) else 0
    c4.metric("Remote or hybrid", f"{flex:.0f}%", help="Share among roles that STATE a work mode.")
    st.caption(f"Work mode is stated in only {len(stated) / len(df) * 100:.0f}% of these roles, "
               "so treat that percentage with care. Missing information is shown as 'Not stated', never guessed.")
    a, b = st.columns(2)
    fam = df["role_family"].value_counts().reset_index()
    fam.columns = ["Role family", "Roles"]
    a.plotly_chart(px.pie(fam, names="Role family", values="Roles", hole=0.5, title="Role mix"),
                   width="stretch")
    co = known_co["company"].value_counts().head(10).reset_index()
    co.columns = ["Company", "Roles"]
    b.plotly_chart(px.bar(co.iloc[::-1], x="Roles", y="Company", orientation="h", title="Top hiring companies"),
                   width="stretch")
    if df["period"].iloc[0] == "2023":
        m = df.assign(month=df["first_posted"].str[:7]).groupby("month").size().reset_index(name="Roles")
        show(px.line(m, x="month", y="Roles", markers=True, title="Unique roles by month (2023)"),
                        width="stretch")

# ---------- cities ----------
with tab_city:
    cities = df[~df["city_group"].isin(NOT_CITY)]["city_group"].value_counts().reset_index()
    cities.columns = ["City", "Roles"]
    st.caption(f"{len(df) - cities['Roles'].sum():,} roles have no city (remote or not stated) and are left out here. "
               "Cities with under 3 roles are grouped as 'Other cities'.")
    m = cities[cities["City"].isin(CITY_LATLON)].copy()
    if len(m):
        m["lat"] = m["City"].map(lambda c: CITY_LATLON[c][0])
        m["lon"] = m["City"].map(lambda c: CITY_LATLON[c][1])
        fig = px.scatter_geo(m, lat="lat", lon="lon", size="Roles", hover_name="City", size_max=45,
                             scope="asia", title="Where the roles are")
        fig.update_geos(lonaxis_range=[67, 98], lataxis_range=[6, 36])
        show(fig, width="stretch")
    show(px.bar(cities.head(15).iloc[::-1], x="Roles", y="City", orientation="h",
                           title="Top cities (unique roles)"), width="stretch")

# ---------- skills ----------
with tab_skill:
    ids = set(df["job_id"])
    sk = skills[skills["job_id"].isin(ids)]
    top = sk["skill"].value_counts().head(15).reset_index()
    top.columns = ["Skill", "Roles"]
    top["% of roles"] = (top["Roles"] / len(df) * 100).round(1)
    show(px.bar(top.iloc[::-1], x="% of roles", y="Skill", orientation="h",
                           title="Skills asked for (% of unique roles)"), width="stretch")
    if period_label.startswith("Live"):
        st.caption("Live skills come from job descriptions (JSearch) or short snippets (Jooble).")
    else:
        st.caption("Archive skills come from the skill list in the 2023 dataset.")

# ---------- work mode ----------
with tab_work:
    wm = df["work_mode"].value_counts().reset_index()
    wm.columns = ["Work mode", "Roles"]
    wm_stated = df[df["work_mode"] != "Not stated"]
    show(px.bar(wm, x="Work mode", y="Roles", title="Roles by work mode"), width="stretch")
    st.caption(f"Work mode is stated in {len(wm_stated) / len(df) * 100:.0f}% of these roles "
               f"({len(wm_stated):,} of {len(df):,}). The rest are 'Not stated', never guessed.")
    if len(wm_stated):
        top_cities = wm_stated[~wm_stated["city_group"].isin(NOT_CITY | {"Other cities"})]["city_group"].value_counts().head(8).index
        mix = (wm_stated[wm_stated["city_group"].isin(top_cities)]
               .groupby(["city_group", "work_mode"]).size().reset_index(name="Roles"))
        if len(mix):
            show(px.bar(mix, x="Roles", y="city_group", color="work_mode", orientation="h",
                                   title="Work mode by city (roles that state it)",
                                   labels={"city_group": "City", "work_mode": "Work mode"}), width="stretch")
        flex_jobs = wm_stated[wm_stated["work_mode"].isin(["Remote", "Hybrid"])].sort_values("last_posted", ascending=False)
        st.subheader(f"Remote and hybrid roles ({len(flex_jobs):,})")
        if len(flex_jobs):
            t = flex_jobs[["title", "company", "city", "work_mode", "publisher", "last_posted", "url"]].head(200)
            t.columns = ["Title", "Company", "City", "Work mode", "Source", "Last posted", "Apply"]
            st.dataframe(t, width="stretch", hide_index=True,
                         column_config={"Apply": st.column_config.LinkColumn("Apply", display_text="Open")})
    if not period_label.startswith("Live"):
        st.caption("Archive (2023) work mode comes from job titles and the remote flag only, so it is not "
                   "comparable with live data.")

# ---------- experience and freshers ----------
with tab_exp:
    order = ["Entry", "Mid", "Senior", "Not stated"]
    ex = df["experience_level"].value_counts().reindex(order).fillna(0).reset_index()
    ex.columns = ["Experience", "Roles"]
    ex_stated = df[df["experience_level"] != "Not stated"]
    entry = df[df["experience_level"] == "Entry"]
    e1, e2, e3 = st.columns(3)
    e1.metric("Entry-level / fresher roles", f"{len(entry):,}")
    e2.metric("Share of roles that state a level",
              f"{len(entry) / len(ex_stated) * 100:.0f}% entry" if len(ex_stated) else "-")
    e3.metric("Roles stating a level", f"{len(ex_stated) / len(df) * 100:.0f}%")
    show(px.bar(ex, x="Experience", y="Roles", title="Roles by experience level"), width="stretch")
    st.caption("Entry = under 2 years asked, Mid = 2 to under 5, Senior = 5 or more, or the title says so. "
               "'Not stated' means the posting does not say.")
    if len(entry):
        esk = skills[skills["job_id"].isin(set(entry["job_id"]))]["skill"].value_counts().head(10).reset_index()
        esk.columns = ["Skill", "Roles"]
        esk["% of entry roles"] = (esk["Roles"] / len(entry) * 100).round(1)
        if len(esk):
            show(px.bar(esk.iloc[::-1], x="% of entry roles", y="Skill", orientation="h",
                                   title="Skills asked for in entry-level roles"), width="stretch")
        st.subheader("Entry-level / fresher roles")
        t = entry.sort_values("last_posted", ascending=False)[
            ["title", "company", "city", "work_mode", "publisher", "last_posted", "url"]].head(300)
        t.columns = ["Title", "Company", "City", "Work mode", "Source", "Last posted", "Apply"]
        st.dataframe(t, width="stretch", hide_index=True,
                     column_config={"Apply": st.column_config.LinkColumn("Apply", display_text="Open")})
    if not period_label.startswith("Live"):
        st.caption("Archive (2023) experience comes from job titles only, so there is no 'Mid' level.")

# ---------- then vs now ----------
with tab_then:
    st.caption("Compares ALL archive (2023) roles with ALL live roles. Sidebar filters do not apply here. "
               "Shares are used (not counts) because the two datasets differ in size.")
    old_j, new_j = jobs[jobs["period"] == "2023"], jobs[jobs["period"] == "live"]
    if old_j.empty or new_j.empty:
        st.info("Needs both archive and live data.")
    else:
        def both(old_s, new_s, name, top=None):
            t = pd.concat([old_s.rename("2023 (archive)"), new_s.rename("Live (now)")], axis=1).fillna(0)
            t = t.assign(_s=t.sum(axis=1)).sort_values("_s", ascending=False).drop(columns="_s")
            t = t.head(top) if top else t
            return t.reset_index(names=name).melt(id_vars=name, var_name="Period", value_name="% of roles")

        def share(frame, col, drop=()):
            s = frame[~frame[col].isin(drop)][col].value_counts()
            return s / s.sum() * 100

        fam = both(share(old_j, "role_family"), share(new_j, "role_family"), "Role family")
        show(px.bar(fam, x="Role family", y="% of roles", color="Period", barmode="group",
                               title="Role mix: then vs now"), width="stretch")

        def skill_share(frame):
            ids = set(frame["job_id"])
            return skills[skills["job_id"].isin(ids)]["skill"].value_counts() / len(frame) * 100

        sk = both(skill_share(old_j), skill_share(new_j), "Skill", top=12)
        show(px.bar(sk, x="Skill", y="% of roles", color="Period", barmode="group",
                               title="Skills asked for: % of unique roles, then vs now"), width="stretch")
        st.caption("2023 skills come from the dataset's skill list. Live skills come from job descriptions, "
                   "so small differences are not proof of change.")

        ct = both(share(old_j, "city", NOT_CITY), share(new_j, "city", NOT_CITY), "City", top=10)
        show(px.bar(ct, x="City", y="% of roles", color="Period", barmode="group",
                               title="Top cities: share of roles that name a city"), width="stretch")

        def flex(frame):
            s = frame[frame["work_mode"] != "Not stated"]
            return (s["work_mode"].isin(["Remote", "Hybrid"]).mean() * 100 if len(s) else 0,
                    len(s) / len(frame) * 100)

        (o_flex, o_st), (n_flex, n_st) = flex(old_j), flex(new_j)
        w1, w2 = st.columns(2)
        w1.metric("2023: remote or hybrid", f"{o_flex:.0f}%", help=f"Among the {o_st:.0f}% of roles that state a work mode.")
        w2.metric("Live: remote or hybrid", f"{n_flex:.0f}%", help=f"Among the {n_st:.0f}% of roles that state a work mode.")
        st.caption("Work mode in 2023 comes from titles and a remote flag only, so these two percentages are "
                   "NOT directly comparable. Experience level is left out for the same reason.")

# ---------- jobs table ----------
with tab_jobs:
    show = df.sort_values("last_posted", ascending=False)[
        ["title", "company", "city", "work_mode", "experience_level", "publisher", "last_posted",
         "repost_count", "url"]]
    show.columns = ["Title", "Company", "City", "Work mode", "Experience", "Source", "Last posted",
                    "Postings", "Apply"]
    cfg = {"Apply": st.column_config.LinkColumn("Apply", display_text="Open")}
    st.dataframe(show.head(500), width="stretch", hide_index=True, column_config=cfg)
    st.caption("Showing the newest 500. Archive (2023) rows have no apply link.")