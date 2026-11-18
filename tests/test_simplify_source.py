"""job-scan Simplify source: filters, first-run window, seen set, merge with JobRight items."""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "job-scan" / "scripts"))

import simplify_source as ss  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 18, 18, 0, tzinfo=UTC)


def row(rid, hours_ago=1, **kw):
    base = {"id": rid, "company_name": "Acme", "title": "Software Engineer Intern", "active": True,
            "is_visible": True, "category": "Software", "terms": ["Summer 2027"],
            "date_posted": int((NOW - dt.timedelta(hours=hours_ago)).timestamp()),
            "url": f"https://boards.example.com/acme/jobs/{rid}?src=simplify", "locations": ["San Diego, CA"]}
    base.update(kw)
    return base


class Scan(unittest.TestCase):
    def test_filters(self):
        rows = [row("a"), row("b", active=False), row("c", is_visible=False), row("d", category="Hardware"),
                row("e", terms=["Fall 2026"]), row("f", terms=["N/A"]), row("g", terms=["Summer '27"])]
        items, _ = ss.scan(rows, {"ids": []}, NOW, ss.DEFAULT_CATEGORIES, "Summer 2027")
        self.assertEqual(sorted(i["id"] for i in items), ["a", "f", "g"])

    def test_first_run_only_recent(self):
        items, ids = ss.scan([row("new", 2), row("old", 72)], None, NOW, ss.DEFAULT_CATEGORIES, "", 24)
        self.assertEqual([i["id"] for i in items], ["new"])
        self.assertEqual(ids, {"new", "old"})  # old ones are marked seen so they never flood a later run

    def test_seen_ids_skipped(self):
        items, ids = ss.scan([row("a"), row("b")], {"ids": ["a"]}, NOW, ss.DEFAULT_CATEGORIES)
        self.assertEqual([i["id"] for i in items], ["b"])
        self.assertEqual(ids, {"a", "b"})

    def test_item_shape(self):
        it = ss.to_item(row("a", 3, sponsorship="Offers Sponsorship"))
        self.assertEqual(it["source"], "simplify")
        self.assertEqual(it["job_key"], "simplify:a")
        self.assertEqual(it["term_text"], "Summer 2027")
        self.assertEqual(it["first_seen"], (NOW - dt.timedelta(hours=3)).isoformat())
        self.assertEqual(it["apply_url"], it["link"])
        self.assertEqual(it["location"], "San Diego, CA")


class Merge(unittest.TestCase):
    def test_skips_same_posting_from_jobright(self):
        with tempfile.TemporaryDirectory() as d:
            scan = Path(d) / "scan.json"
            scan.write_text(json.dumps({"window": "w", "items": [
                {"job_key": "jr1", "source": "jobright", "apply_url": "https://boards.example.com/acme/jobs/a?gh_src=jr"}]}))
            added = ss.merge(scan, [ss.to_item(row("a")), ss.to_item(row("b"))])
            data = json.loads(scan.read_text())
            self.assertEqual(added, 1)
            self.assertEqual([i["job_key"] for i in data["items"]], ["jr1", "simplify:b"])
            self.assertEqual(data["window"], "w")


class Cli(unittest.TestCase):
    def test_end_to_end_writes_seen_and_merges(self):
        with tempfile.TemporaryDirectory() as d:
            listings = Path(d) / "listings.json"
            listings.write_text(json.dumps([row("a"), row("b", 100)]))
            seen, scan = Path(d) / "state" / "seen.json", Path(d) / "state" / "scan.json"
            args = ["scan", "--seen", str(seen), "--file", str(listings), "--now", NOW.isoformat(),
                    "--merge-into", str(scan), "--term", "Summer 2027"]
            self.assertEqual(ss.main(args), 0)
            self.assertEqual(json.loads(seen.read_text())["ids"], ["a", "b"])
            self.assertEqual([i["id"] for i in json.loads(scan.read_text())["items"]], ["a"])
            self.assertEqual(ss.main(args), 0)  # second run: nothing new, nothing duplicated
            self.assertEqual(len(json.loads(scan.read_text())["items"]), 1)

    def test_bad_source_leaves_seen_alone(self):
        with tempfile.TemporaryDirectory() as d:
            seen = Path(d) / "seen.json"
            self.assertEqual(ss.main(["scan", "--seen", str(seen), "--file", str(Path(d) / "missing.json")]), 1)
            self.assertFalse(seen.exists())


if __name__ == "__main__":
    unittest.main()
