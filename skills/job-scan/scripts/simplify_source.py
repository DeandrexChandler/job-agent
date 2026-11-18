#!/usr/bin/env python3
"""Simplify internship list as a job-scan source. Standard library only.

  simplify_source.py scan --seen <workspace>/state/simplify-seen.json
      [--url URL | --file listings.json] [--categories "Software,AI/ML/Data"]
      [--term "Summer 2027"] [--first-run-hours 24] [--now ISO]
      [--merge-into <workspace>/state/scan-X.json]

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
    a = ap.parse_args(argv)

    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    try:
        listings = load_listings(a.url, a.file)
    except (OSError, ValueError) as e:
        print(json.dumps({"ok": False, "error": f"could not read Simplify listings: {e}"}))
        return 1
    seen_path = Path(a.seen).expanduser()
    seen = load_seen(seen_path)
    items, ids = scan(listings, seen, now, a.categories.split(","), a.term, a.first_run_hours)
    added = merge(Path(a.merge_into).expanduser(), items) if a.merge_into else len(items)
    save_seen(seen_path, ids, now)
    out = {"ok": True, "first_run": seen is None, "new": len(items), "added_to_scan": added}
    if not a.merge_into:
        out["items"] = items
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
