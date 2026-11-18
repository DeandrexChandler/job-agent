"""skills_mode stretch: find Skills terms the master lacks and keep a ranked skills-to-learn list."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "tailor-resume" / "scripts"))

import stretch_skills as ss  # noqa: E402

TEX_MASTER = (ROOT / "skills" / "job-setup" / "assets" / "master-resume.tex").read_text(encoding="utf-8")


def with_terms(extra: str) -> str:
    return TEX_MASTER.replace("\\textbf{Languages}{: ", "\\textbf{Languages}{: " + extra + ", ", 1)


class Stretched(unittest.TestCase):
    def test_master_has_none(self):
        self.assertEqual(ss.stretched(TEX_MASTER, TEX_MASTER), [])

    def test_finds_new_terms_not_alternates(self):
        # "distributed systems" sits in the master's alternate skills bank, so it is the user's own
        copy = with_terms("Rust, GraphQL, distributed systems")
        self.assertEqual(ss.stretched(TEX_MASTER, copy), ["Rust", "GraphQL"])


class Log(unittest.TestCase):
    def test_counts_rank_and_dedupe_per_job(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "skills-to-learn.md"
            ss.record(log, ["Rust", "GraphQL"], "Acme - SWE Intern", set())
            ss.record(log, ["GraphQL"], "Beta - SWE Intern", set())
            ss.record(log, ["GraphQL"], "Beta - SWE Intern", set())  # same job again: no double count
            rows = ss.load(log)
            self.assertEqual(rows["graphql"][1], 2)
            self.assertEqual(rows["rust"][1], 1)
            body = log.read_text()
            self.assertLess(body.index("| GraphQL |"), body.index("| Rust |"))

    def test_learned_term_drops_off(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "skills-to-learn.md"
            ss.record(log, ["Rust"], "Acme", set())
            ss.record(log, [], "Beta", {"rust"})  # the user added Rust to the master
            self.assertNotIn("rust", ss.load(log))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            m, c, log = Path(d) / "m.tex", Path(d) / "c.tex", Path(d) / "prep" / "s.md"
            m.write_text(TEX_MASTER)
            c.write_text(with_terms("GraphQL"))
            self.assertEqual(ss.main(["--master", str(m), "--resume", str(c), "--job", "Acme", "--log", str(log)]), 0)
            self.assertIn("| GraphQL | 1 | Acme |", log.read_text())


if __name__ == "__main__":
    unittest.main()
