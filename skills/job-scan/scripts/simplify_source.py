#!/usr/bin/env python3
"""Simplify internship list as a job-scan source. Standard library only.

  simplify_source.py scan --seen <workspace>/state/simplify-seen.json
      [--url URL | --file listings.json] [--categories "Software,AI/ML/Data"]
      [--term "Summer 2027"] [--first-run-hours 24] [--now ISO]
      [--merge-into <workspace>/state/scan-X.json]
      [--backlog <workspace>/state/simplify-backlog.json --backlog-take 20]
  simplify_source.py backlog --backlog <workspace>/state/simplify-backlog.json --days 20
      [--url URL | --file listings.json] [--categories ...] [--term ...]
      [--first-companies "Sony,Google"] [--now ISO]

Simplify and Pitt CSC publish every listing in one public JSON file on GitHub
(.github/scripts/listings.json in the SimplifyJobs internship repo). This is a
plain download of a public file, not scraping and not a private API.

A scan keeps listings that are active, visible, in one of the categories and
(when --term is given) list that term, then drops every id already in the seen
file. On the first run, with no seen file, it keeps only listings Simplify
added in the last --first-run-hours, so it does not queue thousands of old
postings. Output items use job-scan's shape with source "simplify", so
job-gate treats them like any other posting. --merge-into appends them to a
scan file and skips postings already there (same id or same apply URL).
The seen file is written only after a successful scan.

Backlog: the scan only ever picks up listings that are new since the last run,
so postings that opened weeks ago and are still open would never be seen.
`backlog` loads every active, matching listing Simplify added in the last
--days days into a backlog file, companies named in --first-companies first,
then newest first. Each later `scan --backlog <file> --backlog-take N` moves
the next N of them into the scan with "backlog": true, which tells job-gate to
skip its freshness check for them (they are old by design) and tells the queue
to fill them after fresh postings. The backlog drains a little every run, so
one run never gates hundreds of postings at once.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UTC = dt.timezone.utc
DEFAULT_URL = ("https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
               "dev/.github/scripts/listings.json")
DEFAULT_CATEGORIES = ["Software", "Software Engineering", "AI/ML/Data"]


def load_listings(url: str = "", file: str = "") -> list[dict]:
    if file:
        return json.loads(Path(file).read_text(encoding="utf-8"))
    req = urllib.request.Request(url or DEFAULT_URL, headers={"User-Agent": "job-agent"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed public https URL
        return json.loads(resp.read().decode("utf-8"))


def load_seen(path: Path) -> dict | None:
    """The seen file, or None on a first run."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("ids"), list):
        return None
    return data


def save_seen(path: Path, ids: set[str], now: dt.datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ids": sorted(ids), "last_scan": now.isoformat()}, indent=1), encoding="utf-8")
    tmp.replace(path)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("'", " 20").split())


def term_matches(terms: list, term: str) -> bool:
    """True when the listing names the term. A listing with no usable term passes; job-gate decides it."""
    want = _norm(term)
    named = [t for t in (terms or []) if t and str(t).strip().upper() != "N/A"]
    if not want or not named:
        return True
    return any(want in _norm(str(t)) or _norm(str(t)) in want for t in named)


def norm_url(url: str) -> str:
    """Scheme, host and path only, for spotting one posting found by two sources."""
    p = urllib.parse.urlsplit((url or "").strip())
    return f"{p.netloc.lower()}{p.path.rstrip('/')}" if p.netloc else ""


def to_item(row: dict) -> dict:
    posted = row.get("date_posted")
    first_seen = dt.datetime.fromtimestamp(int(posted), UTC).isoformat() if posted else ""
    terms = [t for t in row.get("terms") or [] if t and str(t).upper() != "N/A"]
    item = {
        "job_key": f"simplify:{row['id']}",
        "id": row["id"],
        "company": row.get("company_name", ""),
        "title": row.get("title", ""),
        "location": "; ".join(row.get("locations") or []),
        "pay_text": "",
        "first_seen": first_seen,
        "link": row.get("url", ""),
        "apply_url": row.get("url", ""),
        "source": "simplify",
        "kind": "job",
        "category": row.get("category", ""),
    }
    if terms:
        item["term_text"] = ", ".join(terms)
    if row.get("sponsorship"):
        item["sponsorship"] = row["sponsorship"]
    return item


def scan(listings: list[dict], seen: dict | None, now: dt.datetime, categories: list[str],
         term: str = "", first_run_hours: float = 24) -> tuple[list[dict], set[str]]:
    """Return (new items, the full seen-id set to save)."""
    cats = {c.strip().lower() for c in categories if c.strip()}
    seen_ids = set(seen["ids"]) if seen else set()
    cutoff = None if seen else now - dt.timedelta(hours=first_run_hours)
    items = []
    for row in listings:
        rid = str(row.get("id") or "")
        if not rid:
            continue
        if not row.get("active") or not row.get("is_visible", True):
            continue
        if cats and str(row.get("category", "")).lower() not in cats:
            continue
        if not term_matches(row.get("terms") or [], term):
            continue
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        if cutoff is not None:
            posted = row.get("date_posted")
            if not posted or dt.datetime.fromtimestamp(int(posted), UTC) < cutoff:
                continue
        items.append(to_item(row))
    items.sort(key=lambda i: i["first_seen"], reverse=True)
    return items, seen_ids


def build_backlog(listings: list[dict], now: dt.datetime, days: float, categories: list[str],
                  term: str = "", first_companies: list[str] | None = None) -> list[dict]:
    """Every active, matching listing added in the last `days` days, priority companies first, then newest."""
    items, _ = scan(listings, {"ids": []}, now, categories, term)
    cutoff = now - dt.timedelta(days=days)
    items = [dict(i, backlog=True) for i in items
             if i["first_seen"] and dt.datetime.fromisoformat(i["first_seen"]) >= cutoff]
    first = [c.strip().lower() for c in (first_companies or []) if c.strip()]

    def rank(i: dict) -> int:
        name = i["company"].lower()
        for n, c in enumerate(first):
            if c in name or name in c:
                return n
        return len(first)

    items.sort(key=lambda i: i["first_seen"], reverse=True)
    items.sort(key=rank)  # stable: newest first within each priority
    return items


def load_backlog(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return data.get("items", []) if isinstance(data, dict) else []


def save_backlog(path: Path, items: list[dict], now: dt.datetime, built: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    data = {"built": built or old.get("built", now.isoformat()), "updated": now.isoformat(), "items": items}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def take_backlog(path: Path, n: int, skip_ids: set[str], now: dt.datetime) -> list[dict]:
    """Pop up to n backlog items, skipping any id the regular scan already picked up."""
    pending = [i for i in load_backlog(path) if str(i.get("id")) not in skip_ids]
    taken, rest = pending[:max(n, 0)], pending[max(n, 0):]
    if path.exists():
        save_backlog(path, rest, now)
    return taken


def merge(scan_path: Path, items: list[dict]) -> int:
    """Append items to a scan file, skipping postings it already holds. Returns how many were added."""
    data = {"window": "", "items": []}
    if scan_path.exists():
        loaded = json.loads(scan_path.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {"window": "", "items": loaded}
    have_keys = {i.get("job_key") for i in data["items"]}
    have_urls = {norm_url(i.get("apply_url") or i.get("link") or "") for i in data["items"]} - {""}
    added = 0
    for it in items:
        u = norm_url(it["apply_url"])
        if it["job_key"] in have_keys or (u and u in have_urls):
            continue
        data["items"].append(it)
        have_keys.add(it["job_key"])
        if u:
            have_urls.add(u)
        added += 1
    scan_path.parent.mkdir(parents=True, exist_ok=True)
    scan_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--seen", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--file", default="", help="local listings.json, for tests or offline runs")
    p.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES))
    p.add_argument("--term", default="")
    p.add_argument("--first-run-hours", type=float, default=24)
    p.add_argument("--now", default="")
    p.add_argument("--merge-into", default="")
    p.add_argument("--backlog", default="", help="backlog file to drain a little each run")
    p.add_argument("--backlog-take", type=int, default=20)
    b = sub.add_parser("backlog")
    b.add_argument("--backlog", required=True)
    b.add_argument("--days", type=float, default=20)
    b.add_argument("--url", default="")
    b.add_argument("--file", default="")
    b.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES))
    b.add_argument("--term", default="")
    b.add_argument("--first-companies", default="")
    b.add_argument("--now", default="")
    a = ap.parse_args(argv)

    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        listings = load_listings(a.url, a.file)
    except (OSError, ValueError) as e:
        print(json.dumps({"ok": False, "error": f"could not read Simplify listings: {e}"}))
        return 1
    if a.cmd == "backlog":
        items = build_backlog(listings, now, a.days, a.categories.split(","), a.term,
                              a.first_companies.split(",") if a.first_companies else [])
        save_backlog(Path(a.backlog).expanduser(), items, now, built=now.isoformat())
        companies = len({i["company"] for i in items})
        print(json.dumps({"ok": True, "backlog": len(items), "companies": companies, "days": a.days}, indent=1))
        return 0
    seen_path = Path(a.seen).expanduser()
    seen = load_seen(seen_path)
    items, ids = scan(listings, seen, now, a.categories.split(","), a.term, a.first_run_hours)
    from_backlog: list[dict] = []
    if a.backlog:
        from_backlog = take_backlog(Path(a.backlog).expanduser(), a.backlog_take, {str(i["id"]) for i in items}, now)
    added = merge(Path(a.merge_into).expanduser(), items + from_backlog) if a.merge_into else len(items) + len(from_backlog)
    save_seen(seen_path, ids, now)
    out = {"ok": True, "first_run": seen is None, "new": len(items), "from_backlog": len(from_backlog),
           "backlog_left": len(load_backlog(Path(a.backlog).expanduser())) if a.backlog else 0,
           "added_to_scan": added}
    if not a.merge_into:
        out["items"] = items + from_backlog
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
