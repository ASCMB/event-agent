# Minimal Event Agent (Göteborg) – läser RSS/ICS, filtrerar "frukost/mingel", exporterar CSV + MD
import csv, hashlib, re, sys, requests, feedparser, yaml
from datetime import datetime, timedelta, timezone
from icalendar import Calendar
from dateutil import parser as dateparser
import os

KEYWORDS = re.compile(r"(frukost|breakfast|mingel|seminar|seminarium|nätverk|network)", re.I)
CITY     = re.compile(r"(göteborg|gothenburg|lindholmen|hisings|mölndal)", re.I)

def norm(s): return re.sub(r"\s+", " ", (s or "").strip()) if s else ""

def make_id(title, start_dt, org=""):
    key = f"{norm(title).lower()}|{start_dt or ''}|{norm(org).lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()

def parse_rss(url, category=None):
    d = feedparser.parse(url)
    for e in d.entries:
        title = norm(getattr(e, "title", ""))
        desc  = norm(getattr(e, "summary", ""))
        link  = getattr(e, "link", url)
        dt_raw = getattr(e, "published", None) or getattr(e, "updated", None) or getattr(e, "date", None)
        dt = dateparser.parse(dt_raw) if dt_raw else None
        yield dict(source="rss", source_url=url, title=title, start_dt=dt.isoformat() if dt else "",
                   end_dt="", location="", city="", organizer="", category=category or "",
                   price="", registration_url=link, description=desc)

def parse_ics(url, category=None):
    r = requests.get(url, timeout=30); r.raise_for_status()
    cal = Calendar.from_ical(r.content)
    for comp in cal.walk("vevent"):
        title = norm(str(comp.get("summary",""))); loc = norm(str(comp.get("location","")))
        desc  = norm(str(comp.get("description","")))
        start = comp.get("dtstart"); end = comp.get("dtend")
        sd = start.dt.isoformat() if hasattr(start, "dt") else ""
        ed = end.dt.isoformat() if end and hasattr(end, "dt") else ""
        yield dict(source="ics", source_url=url, title=title, start_dt=sd, end_dt=ed,
                   location=loc, city="", organizer="", category=category or "",
                   price="", registration_url=url, description=desc)

def load_sources(path):
    with open(path, "r", encoding="utf-8") as f: return yaml.safe_load(f) or []

def looks_relevant(rec):
    return True
    blob = " ".join([rec.get("title",""), rec.get("description",""), rec.get("location","")])
    return bool(KEYWORDS.search(blob)) and bool(CITY.search(blob) or "göteborg" in blob.lower())

def within_horizon(rec, days=60):
    sd = rec.get("start_dt","")
    if not sd: return True
    try:
        dt = dateparser.parse(sd); now = datetime.now(timezone.utc)
        return dt >= (now - timedelta(days=1)) and dt <= (now + timedelta(days=days))
    except Exception: return True

def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = make_id(r.get("title",""), r.get("start_dt",""), r.get("organizer","")); r["id"]=key
        if key in seen: continue
        seen.add(key); out.append(r)
    return out

def run(sources_file="sources.yml", out_dir="out", days=60):
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for s in load_sources(sources_file):
        t, url, cat = s.get("type"), s.get("url"), s.get("category")
        try:
            if t=="rss":
                rows.extend(list(parse_rss(url, cat)))
            elif t=="ics":
                rows.extend(list(parse_ics(url, cat)))
        except Exception as e:
            print(f"[WARN] {url}: {e}", file=sys.stderr)

    rows = [r for r in rows if looks_relevant(r) and within_horizon(r, days)]
    rows = dedupe(rows)
    # sortera
    def key(r):
        try: return dateparser.parse(r.get("start_dt",""))
        except: return datetime.max
    rows.sort(key=key)

    # CSV
    cols = ["title","start_dt","end_dt","location","city","organizer","category","price","registration_url","source","source_url","description","id"]
    with open(os.path.join(out_dir, "events.csv"), "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in cols})

    # Markdown
    with open(os.path.join(out_dir, "events.md"), "w", encoding="utf-8") as f:
        if not rows:
            f.write("# Inga matchande event just nu.\n")
        else:
            f.write("# Göteborg – kommande frukostar & mingel\n\n")
            for r in rows:
                f.write(f"- **{r.get('title','(utan titel)')}** — {r.get('start_dt','?')}\n  Plats: {r.get('location','?')}\n  Länk: {r.get('registration_url','')}\n\n")

if __name__ == "__main__":
    run()
