#!/usr/bin/env python3
"""Summarize the websites you viewed in Google Chrome on a given day.

Reads Chrome's local `History` SQLite database (read-only, on a temp copy so
it works while Chrome is running). Standard library only.

Usage:
    python chrome_summary.py                  # today
    python chrome_summary.py --date 2026-10-01
    python chrome_summary.py --days 7         # one summary per day, last 7 days
    python chrome_summary.py --profile "Profile 1"
    python chrome_summary.py --history-file /path/to/History
    python chrome_summary.py --json
"""
import argparse
import collections
import datetime as dt
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from urllib.parse import urlparse

# Chrome stores times as microseconds since 1601-01-01 UTC.
CHROME_EPOCH = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)

CATEGORIES = {
    "Search": ["google.", "bing.com", "duckduckgo.com", "search.brave.com", "yahoo.com"],
    "Email & Calendar": ["mail.google.com", "outlook.", "calendar.google.com", "proton.me"],
    "Work & Docs": ["docs.google.com", "drive.google.com", "notion.so", "slack.com",
                    "atlassian.net", "jira", "confluence", "office.com", "zoom.us", "teams.microsoft.com"],
    "Development": ["github.com", "gitlab.com", "stackoverflow.com", "stackexchange.com",
                    "developer.mozilla.org", "npmjs.com", "pypi.org", "docs.python.org", "localhost"],
    "Video & Streaming": ["youtube.com", "youtu.be", "netflix.com", "twitch.tv", "vimeo.com", "disneyplus.com"],
    "Social": ["facebook.com", "instagram.com", "twitter.com", "x.com", "reddit.com",
               "linkedin.com", "tiktok.com", "threads.net", "bsky.app"],
    "News": ["nytimes.com", "bbc.", "cnn.com", "theguardian.com", "reuters.com", "bloomberg.com",
             "news.ycombinator.com", "lapresse.ca", "radio-canada.ca", "cbc.ca"],
    "Shopping": ["amazon.", "ebay.", "etsy.com", "walmart.", "aliexpress.com", "costco."],
    "Reference & Learning": ["wikipedia.org", "coursera.org", "udemy.com", "khanacademy.org", "medium.com"],
    "AI Tools": ["claude.ai", "chatgpt.com", "openai.com", "gemini.google.com", "huggingface.co", "perplexity.ai"],
}


def default_history_dirs(profile):
    system = platform.system()
    home = os.path.expanduser("~")
    if system == "Windows":
        bases = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")]
    elif system == "Darwin":
        bases = [os.path.join(home, "Library", "Application Support", "Google", "Chrome")]
    else:
        bases = [os.path.join(home, ".config", "google-chrome"),
                 os.path.join(home, ".config", "chromium"),
                 os.path.join(home, "snap", "chromium", "common", "chromium")]
    return [os.path.join(b, profile, "History") for b in bases]


def find_history(profile, explicit):
    if explicit:
        return explicit
    for path in default_history_dirs(profile):
        if os.path.isfile(path):
            return path
    sys.exit("Could not find Chrome's History file. Tried:\n  "
             + "\n  ".join(default_history_dirs(profile))
             + "\nUse --history-file or --profile.")


def to_chrome_time(d):
    return int((d - CHROME_EPOCH).total_seconds() * 1_000_000)


def categorize(host):
    for cat, needles in CATEGORIES.items():
        if any(n in host for n in needles):
            return cat
    return "Other"


def load_visits(history_path, start, end):
    """Return visits in [start, end) as dicts (local-time aware datetimes)."""
    tmpdir = tempfile.mkdtemp(prefix="chrome_hist_")
    try:
        copy = os.path.join(tmpdir, "History")
        shutil.copy2(history_path, copy)  # Chrome locks the live file
        con = sqlite3.connect(copy)
        rows = con.execute(
            """SELECT u.url, u.title, v.visit_time, v.visit_duration
               FROM visits v JOIN urls u ON u.id = v.url
               WHERE v.visit_time >= ? AND v.visit_time < ?
               ORDER BY v.visit_time""",
            (to_chrome_time(start), to_chrome_time(end)),
        ).fetchall()
        con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    visits = []
    for url, title, vt, dur in rows:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        visits.append({
            "url": url, "title": (title or "").strip(), "host": host,
            "time": (CHROME_EPOCH + dt.timedelta(microseconds=vt)).astimezone(),
            "seconds": (dur or 0) / 1_000_000,
        })
    return visits


def summarize(visits):
    by_host = collections.OrderedDict()
    for v in visits:
        h = by_host.setdefault(v["host"], {"visits": 0, "seconds": 0.0, "titles": collections.Counter()})
        h["visits"] += 1
        h["seconds"] += v["seconds"]
        if v["title"]:
            h["titles"][v["title"]] += 1
    cats = collections.Counter()
    cat_secs = collections.Counter()
    for host, h in by_host.items():
        c = categorize(host)
        cats[c] += h["visits"]
        cat_secs[c] += h["seconds"]
    hours = collections.Counter(v["time"].hour for v in visits)
    sites = sorted(by_host.items(), key=lambda kv: (-kv[1]["seconds"], -kv[1]["visits"]))
    return {
        "total_visits": len(visits),
        "unique_sites": len(by_host),
        "first": visits[0]["time"] if visits else None,
        "last": visits[-1]["time"] if visits else None,
        "sites": sites, "categories": cats, "category_seconds": cat_secs, "hours": hours,
    }


def fmt_dur(sec):
    sec = int(sec)
    if sec < 60:
        return f"{sec}s" if sec else "-"
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def print_report(day, s, top):
    print(f"\n=== Chrome history for {day:%A %Y-%m-%d} ===")
    if not s["total_visits"]:
        print("No visits recorded.")
        return
    print(f"{s['total_visits']} page visits across {s['unique_sites']} sites, "
          f"active {s['first']:%H:%M} - {s['last']:%H:%M}")

    print("\nBy category:")
    for cat, n in s["categories"].most_common():
        t = s["category_seconds"][cat]
        print(f"  {cat:<22} {n:>4} visits  {fmt_dur(t):>8}")

    print(f"\nTop {top} sites (by time on page, then visits):")
    for host, h in s["sites"][:top]:
        title = h["titles"].most_common(1)[0][0] if h["titles"] else ""
        print(f"  {host:<32} {h['visits']:>4} visits  {fmt_dur(h['seconds']):>8}  {title[:50]}")

    peak = s["hours"].most_common(3)
    print("\nBusiest hours: " + ", ".join(f"{h:02d}:00 ({n})" for h, n in peak))
    mx = max(s["hours"].values())
    print("\nActivity by hour:")
    for hr in range(24):
        n = s["hours"].get(hr, 0)
        if n:
            print(f"  {hr:02d}h {'#' * max(1, round(30 * n / mx))} {n}")


def to_json(day, s, top):
    return {
        "date": day.isoformat(),
        "total_visits": s["total_visits"], "unique_sites": s["unique_sites"],
        "first_visit": s["first"].isoformat() if s["first"] else None,
        "last_visit": s["last"].isoformat() if s["last"] else None,
        "categories": dict(s["categories"]),
        "top_sites": [{"site": h, "visits": d["visits"], "seconds": round(d["seconds"]),
                       "top_title": d["titles"].most_common(1)[0][0] if d["titles"] else ""}
                      for h, d in s["sites"][:top]],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", help="YYYY-MM-DD (local time). Default: today")
    p.add_argument("--days", type=int, default=1, help="number of days ending at --date (default 1)")
    p.add_argument("--profile", default="Default", help='Chrome profile dir name (default "Default")')
    p.add_argument("--history-file", help="explicit path to a Chrome History file")
    p.add_argument("--top", type=int, default=15, help="number of top sites to list (default 15)")
    p.add_argument("--json", action="store_true", help="output JSON instead of text")
    a = p.parse_args()

    end_day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    path = find_history(a.profile, a.history_file)
    out = []
    for i in range(a.days - 1, -1, -1):
        day = end_day - dt.timedelta(days=i)
        start = dt.datetime.combine(day, dt.time.min).astimezone()
        end = start + dt.timedelta(days=1)
        s = summarize(load_visits(path, start, end))
        if a.json:
            out.append(to_json(day, s, a.top))
        else:
            print_report(day, s, a.top)
    if a.json:
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
