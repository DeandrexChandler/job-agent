"""recruiter-outreach log: daily cap, per-company cap, no second draft, LinkedIn kept hands-off."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "recruiter-outreach" / "scripts"))

import outreach_log as ol  # noqa: E402

TODAY = "2026-11-18"


def person(company="Acme", url="https://www.linkedin.com/in/jane-doe/", kind="recruiter", day=TODAY):
    return {"company": company, "name": "Jane Doe", "url": url, "role": "University Recruiter",
            "kind": kind, "job": "SWE Intern", "drafted_on": day}


class Pick(unittest.TestCase):
    def test_best_fit_first_and_daily_budget(self):
        jobs = [{"company": "Low", "fit": 1}, {"company": "High", "fit": 9}, {"company": "Mid", "fit": 5}]
        got = ol.pick({"people": []}, jobs, TODAY, per_day=3, per_company=2)
        self.assertEqual([(g["company"], g["people_needed"]) for g in got], [("High", 2), ("Mid", 1)])

    def test_counts_drafts_already_made_today_and_per_company(self):
        data = {"people": [person("Acme Inc."), person("Beta", "https://linkedin.com/in/b")]}
        jobs = [{"company": "Acme", "fit": 9}, {"company": "Beta"}, {"company": "Gamma"}]
        got = ol.pick(data, jobs, TODAY, per_day=4, per_company=1)
        self.assertEqual([g["company"] for g in got], ["Gamma"])

    def test_one_entry_per_company(self):
        jobs = [{"company": "Acme", "title": "A"}, {"company": "acme", "title": "B"}]
        self.assertEqual(len(ol.pick({"people": []}, jobs, TODAY, 8, 2)), 1)


class Record(unittest.TestCase):
    def test_no_second_draft_for_same_profile(self):
        data = {"people": []}
        self.assertTrue(ol.record(data, person())[0])
        ok, msg = ol.record(data, person(url="https://linkedin.com/in/jane-doe?trk=x"))
        self.assertFalse(ok)
        self.assertIn("already", msg)

    def test_needs_a_profile_url_and_known_kind(self):
        self.assertFalse(ol.record({"people": []}, person(url="https://example.com/jane"))[0])
        self.assertFalse(ol.record({"people": []}, person(kind="ceo"))[0])

    def test_cli_record_mark_list(self):
        with tempfile.TemporaryDirectory() as d:
            log = str(Path(d) / "state" / "log.json")
            base = ["--log", log]
            self.assertEqual(ol.main(["record", *base, "--company", "Acme", "--name", "Jane", "--url",
                                      "https://www.linkedin.com/in/jane", "--role", "Recruiter",
                                      "--kind", "recruiter", "--today", TODAY]), 0)
            self.assertEqual(ol.main(["mark", *base, "--url", "https://linkedin.com/in/jane/", "--status", "sent"]), 0)
            data = json.loads(Path(log).read_text())
            self.assertEqual(data["people"][0]["status"], "sent")
            self.assertEqual(ol.main(["mark", *base, "--url", "https://linkedin.com/in/nobody", "--status", "sent"]), 1)


class SkillRules(unittest.TestCase):
    def test_skill_never_acts_on_linkedin(self):
        text = (ROOT / "skills" / "recruiter-outreach" / "SKILL.md").read_text()
        self.assertIn("The user sends every message", text)
        self.assertIn("Never open a linkedin.com page", text)
        self.assertIn("web search", text)
        self.assertNotIn("—", text)


if __name__ == "__main__":
    unittest.main()
