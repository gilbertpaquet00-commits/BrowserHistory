# BrowserHistory

`chrome_summary.py` summarizes the sites you viewed in Google Chrome in a day: totals, categories, top sites (by time on page), busiest hours. Python 3, no dependencies. Runs locally; nothing leaves your machine.

```
python chrome_summary.py                    # today
python chrome_summary.py --date 2026-10-01
python chrome_summary.py --days 7           # daily summaries for the last week
python chrome_summary.py --profile "Profile 1"
python chrome_summary.py --history-file /path/to/History
python chrome_summary.py --json
```

It copies Chrome's `History` database to a temp file before reading, so Chrome can stay open. Default locations: Linux `~/.config/google-chrome`, macOS `~/Library/Application Support/Google/Chrome`, Windows `%LOCALAPPDATA%\Google\Chrome\User Data`.
Edit `CATEGORIES` in the script to tune site grouping.
