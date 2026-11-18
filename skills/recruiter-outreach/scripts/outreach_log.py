#!/usr/bin/env python3
"""Outreach log for recruiter-outreach: who to research today, who was drafted, who was sent.
Standard library only.

  outreach_log.py pick   --log state/outreach-log.json --jobs jobs.json [--per-day 8] [--per-company 2] [--today YYYY-MM-DD]
  outreach_log.py record --log state/outreach-log.json --company C --name N --url U --role R --kind recruiter|alum|engineer
                         [--job "Title"] [--today YYYY-MM-DD]
  outreach_log.py mark   --log state/outreach-log.json --url U --status sent|replied|skip
  outreach_log.py list   --log state/outreach-log.json [--status drafted]

jobs.json is a list of {"company", "title", "fit"?} for jobs submitted or ready this run.
pick returns the companies to research today, best fit first, with how many people each
still needs, staying under the daily draft cap and skipping companies that already have
--per-company people in the log. record refuses a profile URL that is already logged, so
nobody gets two drafts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

KINDS = ("recruiter", "alum", "engineer")
STATUSES = ("drafted", "sent", "replied", "skip")


def norm_company(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    n = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology)\b", " ", n)
    return " ".join(n.split())


def norm_url(url: str) -> str:
    u = (url or "").strip().lower().split("?")[0].split("#")[0].rstrip("/")
    return re.sub(r"^https?://([a-z]{2,3}\.)?(www\.)?", "", u)


def load(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("people"), list):
                return data
        except ValueError:
            pass
    return {"people": []}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def pick(data: dict, jobs: list[dict], today: str, per_day: int, per_company: int) -> list[dict]:
    drafted_today = sum(1 for p in data["people"] if p.get("drafted_on") == today)
    budget = max(per_day - drafted_today, 0)
    have: dict[str, int] = {}
    for p in data["people"]:
        if p.get("status") != "skip":
            have[norm_company(p["company"])] = have.get(norm_company(p["company"]), 0) + 1
    out, seen = [], set()
    for job in sorted(jobs, key=lambda j: -(j.get("fit") or 0)):
        key = norm_company(job.get("company", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        need = per_company - have.get(key, 0)
        if need <= 0 or budget <= 0:
            continue
        take = min(need, budget)
        budget -= take
        out.append({"company": job["company"], "job": job.get("title", ""), "people_needed": take,
                    "already_in_log": have.get(key, 0)})
    return out


def record(data: dict, person: dict) -> tuple[bool, str]:
    if person["kind"] not in KINDS:
        return False, f"kind must be one of {', '.join(KINDS)}"
    u = norm_url(person["url"])
    if "linkedin.com/in/" not in u:
        return False, "url must be a linkedin.com/in/ profile URL from a search result"
    if any(norm_url(p["url"]) == u for p in data["people"]):
        return False, "already in the log; no second draft"
    data["people"].append({**person, "status": "drafted"})
    return True, "recorded"


def mark(data: dict, url: str, status: str) -> bool:
    u = norm_url(url)
    for p in data["people"]:
        if norm_url(p["url"]) == u:
            p["status"] = status
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pick", "record", "mark", "list"):
        p = sub.add_parser(name)
        p.add_argument("--log", required=True)
        if name == "pick":
            p.add_argument("--jobs", required=True)
            p.add_argument("--per-day", type=int, default=8)
            p.add_argument("--per-company", type=int, default=2)
            p.add_argument("--today", default="")
        if name == "record":
            for f in ("company", "name", "url", "role", "kind"):
                p.add_argument(f"--{f}", required=True)
            p.add_argument("--job", default="")
            p.add_argument("--today", default="")
        if name == "mark":
            p.add_argument("--url", required=True)
            p.add_argument("--status", required=True, choices=STATUSES)
        if name == "list":
            p.add_argument("--status", default="")
    a = ap.parse_args(argv)
    path = Path(a.log).expanduser()
    data = load(path)
    today = getattr(a, "today", "") or dt.date.today().isoformat()

    if a.cmd == "pick":
        jobs = json.loads(Path(a.jobs).expanduser().read_text(encoding="utf-8"))
        print(json.dumps(pick(data, jobs, today, a.per_day, a.per_company), indent=1))
        return 0
    if a.cmd == "record":
        ok, msg = record(data, {"company": a.company, "name": a.name, "url": a.url, "role": a.role,
                                "kind": a.kind, "job": a.job, "drafted_on": today})
        if ok:
            save(path, data)
        print(msg)
        return 0 if ok else 1
    if a.cmd == "mark":
        ok = mark(data, a.url, a.status)
        if ok:
            save(path, data)
        print("updated" if ok else "not in the log")
        return 0 if ok else 1
    rows = [p for p in data["people"] if not a.status or p.get("status") == a.status]
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
