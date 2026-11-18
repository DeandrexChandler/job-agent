#!/usr/bin/env python3
"""Skills-to-learn log for skills_mode: stretch. Standard library only.

  stretch_skills.py --master master.tex --resume copy.tex --job "Company - Role" \
      --log <workspace>/interview-prep/skills-to-learn.md [--json]

With skills_mode: stretch, a tailored copy may list Skills terms the master
never claims. This script finds them (Skills terms in the copy that are in no
Skills row of the master, alternates included) and records each one in a
running Markdown table: the term, how many resumes it went out on, and the
jobs. The table is sorted by count, so the top rows are what to learn first.
A term the user adds to the master later is a real skill and stops counting.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import resume_check  # noqa: E402

HEADER = ("# Skills to learn\n\nSkills a tailored resume listed that your master resume does not. "
          "Learn the top ones before interviews; move a term into your master once you can use it.\n\n"
          "| Skill | Resumes | Jobs |\n| --- | --- | --- |\n")
ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|$")


def stretched(master: str, resume: str) -> list[str]:
    """Skills terms in the copy that no Skills row of the master (alternates included) holds, in page order."""
    have = resume_check.skill_terms(resume_check.parse(resume_check.unwrap_alternates(master))["skills"])
    out, seen = [], set()
    for row in resume_check.parse(resume)["skills"]:
        for t in re.split(r",\s*", row.split(":", 1)[-1]):
            t = t.strip()
            if t and t.lower() not in have and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


def load(path: Path) -> dict[str, tuple[str, int, list[str]]]:
    rows: dict[str, tuple[str, int, list[str]]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line)
            if m and m.group(1) not in ("Skill", "---"):
                jobs = [j.strip() for j in m.group(3).split(";") if j.strip()]
                rows[m.group(1).lower()] = (m.group(1), int(m.group(2)), jobs)
    return rows


def record(path: Path, terms: list[str], job: str, master_terms: set[str]) -> dict[str, tuple[str, int, list[str]]]:
    rows = {k: v for k, v in load(path).items() if k not in master_terms}
    for t in terms:
        name, n, jobs = rows.get(t.lower(), (t, 0, []))
        if job and job in jobs:
            continue
        rows[t.lower()] = (name, n + 1, jobs + ([job] if job else []))
    body = "".join(f"| {name} | {n} | {'; '.join(jobs)} |\n"
                   for name, n, jobs in sorted(rows.values(), key=lambda r: (-r[1], r[0].lower())))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", required=True)
    ap.add_argument("--resume", required=True)
    ap.add_argument("--job", default="")
    ap.add_argument("--log", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    master = Path(a.master).read_text(encoding="utf-8")
    terms = stretched(master, Path(a.resume).read_text(encoding="utf-8"))
    master_terms = resume_check.skill_terms(resume_check.parse(resume_check.unwrap_alternates(master))["skills"])
    record(Path(a.log).expanduser(), terms, a.job, master_terms)
    if a.json:
        print(json.dumps({"stretched": terms}))
    else:
        print("stretched skills: " + (", ".join(terms) if terms else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
