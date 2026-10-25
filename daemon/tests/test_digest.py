import os
import tempfile
import unittest
from unittest.mock import patch

from prs import MONOREPO, finding, pr_review as prr, rq
from pr_wizard import config, db, snapshot

A, B = "a" * 40, "b" * 40
REVIEWERS = ("opus", "codex", "quality")


def digest(findings, rnd=1):
    return prr.digest(findings, rnd)


class Digest(unittest.TestCase):
    def test_no_findings(self):
        self.assertEqual(digest([]), {"counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                                      "at_floor": 0, "top": []})

    def test_notes_only_has_findings_but_none_at_the_floor(self):
        d = digest([finding("low"), finding("medium", confidence=0.59)])
        self.assertEqual((d["counts"]["low"], d["counts"]["medium"], d["at_floor"], len(d["top"])), (1, 1, 0, 2))

    def test_the_floor_rises_from_round_4(self):
        fs = [finding("medium"), finding("high")]
        self.assertEqual([digest(fs, r)["at_floor"] for r in (3, 4)], [2, 1])
        self.assertEqual(digest(fs, 4)["at_floor"], len(prr.to_fix(fs, 4)))

    def test_mixed_severities_count_and_rank(self):
        fs = [finding("low", title="l"), finding("critical", title="c"), finding("medium", title="m1"),
              finding("high", title="h"), finding("medium", title="m2")]
        d = digest(fs)
        self.assertEqual(d["counts"], {"critical": 1, "high": 1, "medium": 2, "low": 1})
        self.assertEqual(d["at_floor"], 4)
        self.assertEqual([t["title"] for t in d["top"]], ["c", "h", "m1"])

    def test_confidence_orders_within_a_severity_and_ties_keep_the_report_order(self):
        fs = [finding("medium", 0.7, title="x"), finding("medium", 0.9, title="y"), finding("medium", 0.7, title="z")]
        self.assertEqual([t["title"] for t in digest(fs)["top"]], ["y", "x", "z"])

    def test_a_top_entry_has_severity_title_file_and_line(self):
        d = digest([finding("high", file="b.py", line_start=7, title="boom")])
        self.assertEqual(d["top"], [{"severity": "high", "title": "boom", "file": "b.py", "line": 7}])

    def test_post_returns_the_digest_on_every_path(self):
        sc = {"base_sha": None, "head": A, "base_branch": "main", "round": 1}
        with patch.object(prr, "commentable_lines", return_value={}):
            empty = prr.post(5, "opus", {"findings": [], "summary": "s"}, sc, dry_run=True)
            some = prr.post(5, "opus", {"findings": [finding("low")], "summary": "s"}, sc, dry_run=True)
        self.assertEqual(empty["digest"]["at_floor"], 0)
        self.assertEqual((some["stop"], some["digest"]["counts"]["low"]), (True, 1))

    def test_unparsed_engine_output_posts_instead_of_raising(self):
        sc = {"base_sha": None, "head": A, "base_branch": "main", "round": 1}
        fs = [finding("info", title="i"), finding("High", title="h"), finding("medium", confidence=None, title="n")]
        with patch.object(prr, "commentable_lines", return_value={}):
            res = prr.post(5, "opus", {"findings": fs, "summary": "s"}, sc, dry_run=True)
        self.assertEqual(res["digest"]["counts"], {"critical": 0, "high": 1, "medium": 1, "low": 1})
        self.assertEqual((res["digest"]["at_floor"], res["stop"]), (1, False))
        self.assertEqual([t["title"] for t in res["digest"]["top"]], ["h", "n", "i"])


class Stored(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        patcher = patch.object(db, "DB", os.path.join(self.dir.name, "state.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db.close)
        self.addCleanup(self.dir.cleanup)

    def run_review(self, outputs):
        with patch.object(rq, "run_reviewer", side_effect=lambda repo, n, r: outputs[r]):
            return rq.review(MONOREPO, 5, A)

    def test_each_reviewer_row_is_stored_for_the_reviewed_sha(self):
        d = digest([finding("medium")])
        outputs = {"opus": {"posted": True, "stop": False, "engine": "claude", "round": 2, "url": "u", "digest": d},
                   "codex": {"posted": True, "stop": True, "reason": "notes-only", "engine": "codex", "round": 2,
                             "url": "v", "digest": digest([finding("low")], 2)},
                   "quality": {"posted": False, "stop": True, "reason": "no-findings", "engine": "claude", "round": 2,
                               "summary": "x" * 50, "digest": digest([])}}
        self.assertEqual(self.run_review(outputs), ("posted", "opus"))
        rows = db.reviewer_results(MONOREPO, 5)
        self.assertEqual({k: (r["result"], r["sha"]) for k, r in rows.items()},
                         {"opus": ("posted", A), "codex": ("notes-only", A), "quality": ("clean", A)})
        self.assertEqual((rows["opus"]["engine"], rows["opus"]["round"], rows["opus"]["url"], rows["opus"]["digest"]),
                         ("claude", 2, "u", d))
        self.assertIsNone(rows["quality"]["url"])

    def test_a_skipped_run_keeps_the_stored_row(self):
        d = digest([finding("high")])
        db.put_reviewer_result(MONOREPO, 5, A, "opus", {"result": "posted", "engine": "claude", "round": 1,
                                                        "digest": d, "url": "u"})
        skipped = {"posted": False, "skipped": "already-reviewed", "stop": False}
        self.run_review({r: skipped for r in REVIEWERS})
        row = db.reviewer_results(MONOREPO, 5)["opus"]
        self.assertEqual((row["result"], row["digest"], row["url"]), ("posted", d, "u"))

    def test_the_conventions_of_a_run_land_in_its_row_and_the_snapshot(self):
        files = ["AGENTS.md", "ui/AGENTS.md"]
        outputs = {r: {"stop": True, "reason": "no-findings", "engine": "claude", "round": 1, "digest": digest([]),
                       "conventions": files} for r in REVIEWERS}
        self.run_review(outputs)
        rows = db.reviewer_results(MONOREPO, 5)
        self.assertEqual([r["conventions"] for r in rows.values()], [files] * 3)
        found = snapshot.findings(MONOREPO, {}, rows, A, config.load().config)
        self.assertEqual(found["conventions"], files)

    def test_a_run_skipped_for_lack_of_conventions_stores_a_skipped_row(self):
        skipped = {"reviewer": "quality", "round": 2, "posted": False, "stop": True, "reason": "no-conventions",
                   "conventions": []}
        clean = {"stop": True, "reason": "no-findings", "engine": "claude", "round": 2, "digest": digest([]),
                 "conventions": []}
        self.assertEqual(self.run_review({"opus": clean, "codex": clean, "quality": skipped}), ("clean", "no findings"))
        rows = db.reviewer_results(MONOREPO, 5)
        self.assertEqual((rows["quality"]["result"], rows["quality"]["digest"], rows["quality"]["round"],
                          rows["quality"]["sha"]), ("skipped", None, 2, A))
        found = snapshot.findings(MONOREPO, {}, rows, A, config.load().config)
        quality = next(r for r in found["reviewers"] if r["id"] == "quality")
        self.assertEqual((quality["result"], quality["counts"], quality["top"], quality["url"], quality["engine"]),
                         ("skipped", snapshot.EMPTY["counts"], [], None, "claude"))
        self.assertEqual(found["conventions"], [])

    def test_a_new_head_replaces_the_older_rows(self):
        db.put_reviewer_result(MONOREPO, 5, B, "opus", {"result": "posted", "digest": digest([])})
        self.run_review({r: {"stop": True, "reason": "no-findings", "round": 1, "digest": digest([])}
                         for r in REVIEWERS})
        self.assertEqual({r["sha"] for r in db.reviewer_results(MONOREPO, 5).values()}, {A})

    def test_failed_and_limited_runs_store_nothing(self):
        outputs = {"opus": None, "codex": rq.LIMITED, "quality": None}
        self.assertEqual(self.run_review(outputs)[0], "limited")
        self.assertEqual(db.reviewer_results(MONOREPO, 5), {})


if __name__ == "__main__":
    unittest.main()
