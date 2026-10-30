"""Text helpers: find skills in a job posting, guess the experience level,
and tidy up city names. Plain keyword rules, so every result can be explained."""
import html
import re

# skill name -> regex patterns (matched case-insensitively on whole words)
SKILL_PATTERNS = {
    "SQL": [r"\bsql\b"],
    "MySQL": [r"\bmysql\b"],
    "PostgreSQL": [r"\bpostgre(?:s|sql)\b"],
    "Excel": [r"\bexcel\b"],
    "Python": [r"\bpython\b"],
    "R": [r"\br programming\b", r"\br language\b", r"\brstudio\b"],
    "Power BI": [r"\bpower\s?-?\s?bi\b"],
    "Tableau": [r"\btableau\b"],
    "Looker Studio": [r"\blooker(?:\s+studio)?\b", r"\bdata studio\b"],
    "Qlik": [r"\bqlik(?:\s?view|\s?sense)?\b"],
    "Statistics": [r"\bstatistic(?:s|al)?\b"],
    "Machine Learning": [r"\bmachine learning\b", r"\bml\b"],
    "Pandas": [r"\bpandas\b"],
    "NumPy": [r"\bnumpy\b"],
    "ETL": [r"\betl\b", r"\belt\b"],
    "Data Visualization": [r"\bdata visuali[sz]ation\b", r"\bdashboards?\b"],
    "AWS": [r"\baws\b", r"\bamazon web services\b", r"\bredshift\b"],
    "Azure": [r"\bazure\b"],
    "Google Cloud": [r"\bgcp\b", r"\bgoogle cloud\b", r"\bbigquery\b"],
    "Snowflake": [r"\bsnowflake\b"],
    "Spark": [r"\bspark\b", r"\bpyspark\b", r"\bdatabricks\b"],
    "Google Sheets": [r"\bgoogle sheets?\b"],
    "VBA / Macros": [r"\bvba\b", r"\bmacros?\b"],
    "SAS": [r"\bsas\b"],
    "SPSS": [r"\bspss\b"],
    "Git": [r"\bgit\b", r"\bgithub\b"],
}
_COMPILED = {
    name: [re.compile(p, re.IGNORECASE) for p in pats]
    for name, pats in SKILL_PATTERNS.items()
}

_TAG = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Adzuna wraps matched search words in <strong> tags; remove them."""
    return _TAG.sub("", text or "")


def extract_skills(text: str) -> list:
    text = strip_html(text)
    found = [name for name, pats in _COMPILED.items() if any(p.search(text) for p in pats)]
    return sorted(found)


_SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|principal|head|manager|director)\b", re.I)
_ENTRY_TITLE = re.compile(r"\b(junior|jr\.?|entry|fresher|freshers|intern|trainee|graduate)\b", re.I)
_NUM = r"(\d{1,2}(?:\.\d)?)"
_SEP = r"\s*(?:\+|-|to|\u2013)?\s*(?:\d{1,2}(?:\.\d)?)?\s*\+?\s*"
# "3-5 years of experience"   and   "Experience required: 3+ years"
# (the word "experience" must be nearby, so "25 years in banking" is ignored)
_YEARS_A = re.compile(_NUM + _SEP + r"(?:years|yrs|year)\b[^.]{0,25}?experience", re.I)
_YEARS_B = re.compile(r"experience[^.\n]{0,40}?" + _NUM + _SEP + r"(?:years|yrs|year)\b", re.I)
_ASSISTANT = re.compile(r"assistant manager", re.I)


def min_years_required(text: str):
    """Lowest 'years of experience' number the text asks for, or None."""
    text = clean_text(text)
    lows = [float(m.group(1)) for rx in (_YEARS_A, _YEARS_B) for m in rx.finditer(text)]
    return min(lows) if lows else None


def classify_experience(title: str, description: str) -> str:
    """Entry / Mid / Senior from the title first, then from the years asked for.
    Under 2 years = Entry, 2 to under 5 = Mid, 5 or more = Senior.
    Returns 'Not stated' when nothing says so (we do not guess)."""
    title = strip_html(title)
    if _SENIOR_TITLE.search(title) and not _ASSISTANT.search(title):
        return "Senior"
    if _ENTRY_TITLE.search(title):
        return "Entry"
    low = min_years_required(description)
    if low is None:
        return "Not stated"
    return "Entry" if low < 2 else "Mid" if low < 5 else "Senior"


# Different spellings and satellite towns -> one label used on the dashboard map
CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "bangalore urban": "Bengaluru",
    "mumbai": "Mumbai", "bombay": "Mumbai", "navi mumbai": "Mumbai", "thane": "Mumbai",
    "delhi": "Delhi", "new delhi": "Delhi",
    "gurgaon": "Gurugram", "gurugram": "Gurugram", "noida": "Noida", "greater noida": "Noida",
    "ghaziabad": "Ghaziabad", "faridabad": "Faridabad",
    "hyderabad": "Hyderabad", "secunderabad": "Hyderabad",
    "chennai": "Chennai", "madras": "Chennai",
    "pune": "Pune", "kolkata": "Kolkata", "calcutta": "Kolkata",
    "ahmedabad": "Ahmedabad", "jaipur": "Jaipur", "lucknow": "Lucknow",
    "indore": "Indore", "kochi": "Kochi", "cochin": "Kochi",
    "chandigarh": "Chandigarh", "mohali": "Mohali", "panchkula": "Panchkula",
}


def normalize_location(area, display_name: str):
    """Return (city, state). `area` is Adzuna's list, e.g. ['India','Karnataka','Bangalore']."""
    parts = [a for a in (area or []) if a]
    parts += [p.strip() for p in (display_name or "").split(",") if p.strip()]
    # most specific first, ignore the country itself
    candidates = [p for p in reversed(parts) if p.lower() != "india"]
    city = None
    for c in candidates:
        if c.lower() in CITY_ALIASES:
            city = CITY_ALIASES[c.lower()]
            break
    if city is None:
        city = candidates[0] if candidates else "Not stated"
    state = area[1] if area and len(area) > 1 else None
    return city, state


_HYBRID = re.compile(r"\bhybrid\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|work-from-home|wfh)\b", re.I)
_ONSITE = re.compile(r"\b(on-?site|work from office|in-?office|office-based)\b", re.I)


def detect_work_mode(text: str) -> str:
    """Remote / Hybrid / On-site only when the text says so; otherwise 'Not stated'."""
    text = strip_html(text)
    if _HYBRID.search(text):
        return "Hybrid"
    if _REMOTE.search(text):
        return "Remote"
    if _ONSITE.search(text):
        return "On-site"
    return "Not stated"


def city_from_text(location: str) -> str:
    """For plain strings like 'Pune, Maharashtra' or 'Gurgaon' (specific part first)."""
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    for p in parts:
        if p.lower() in CITY_ALIASES:
            return CITY_ALIASES[p.lower()]
    for p in parts:
        if p.lower() != "india":
            return p
    return "Not stated"


def clean_text(text: str) -> str:
    """Remove HTML tags/entities (&nbsp; etc.), line breaks and leading dots."""
    text = html.unescape(strip_html(text)).replace(" ", " ")
    text = re.sub(r"\\[rnt]", " ", text)          # literal "\r\n" text some feeds contain
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[\s.…]+", "", text)


# Order matters: the first rule that matches wins.
_ROLE_RULES = [
    ("Data Scientist", re.compile(r"data scien|machine learning|\bml engineer|\bai engineer|\bnlp\b", re.I)),
    ("Data Engineer", re.compile(r"data engineer|\betl\b|big data|data architect|analytics engineer", re.I)),
    ("BI / Reporting", re.compile(r"\bbi\b|business intelligence|reporting|\bmis\b|dashboard|power ?bi|tableau|insights?\b", re.I)),
    ("Business Analyst", re.compile(r"business analy|business systems analy|\bba\b", re.I)),
    ("Data Analyst", re.compile(r"data analy|analytics|analytical|data \w+ analyst", re.I)),
    ("Other analyst", re.compile(r"\banalyst\b", re.I)),
]


def role_family(title: str) -> str:
    """Which kind of analytics job is this title? 'Not analytics' when none fits."""
    title = clean_text(title)
    for name, pattern in _ROLE_RULES:
        if pattern.search(title):
            return name
    return "Not analytics"
