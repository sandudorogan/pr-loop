import json
import unittest
from subprocess import CompletedProcess
from unittest import mock

from prs import HEAD, MONOREPO, pr
from test_db import DbCase
from pr_loop import db, scope
import pr_scope

OLD = "0" * 40
SUMMARY = {"verdict": "focused", "reason": "r", "intent": "i", "stated": "s", "changes": [], "touches": []}


def row(status="ready", sha=HEAD, errors=0):
    return {"sha": sha, "status": status, "errors": errors}


class Due(unittest.TestCase):
    def test_a_head_without_a_summary_is_due(self):
        self.assertTrue(scope.due(pr(), None))
        self.assertTrue(scope.due(pr(), row(sha=OLD)))
        self.assertTrue(scope.due(pr(), row("running")))
        self.assertTrue(scope.due(pr(), row("limited", errors=9)))
        self.assertTrue(scope.due(pr(), row("failed", errors=2)))

    def test_a_summary_or_a_spent_retry_budget_is_not(self):
        self.assertFalse(scope.due(pr(), row()))
        self.assertFalse(scope.due(pr(), row("failed", errors=3)))


class Run(DbCase):
    def setUp(self):
        super().setUp()
        for target, value in (("fingerprint", {"a.py": "x"}), ("child", {}), ("log", None)):
            patcher = mock.patch.object(scope.q, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_with(self, code, stdout="", stderr=""):
        with mock.patch.object(scope.subprocess, "run", return_value=CompletedProcess([], code, stdout, stderr)) as run:
            scope.run(pr(), [])
        return run, db.scope(MONOREPO, 1)

    def test_a_pass_stores_the_summary_of_the_head(self):
        _, got = self.run_with(0, json.dumps(SUMMARY))
        self.assertEqual((got["status"], got["of"], got["summary"], got["files"]), ("ready", HEAD, SUMMARY, {"a.py": "x"}))
        self.assertEqual(scope.item(got, HEAD) | {"at": None},
                         {"status": "ready", "head": HEAD, "current": True, "error": None, "at": None, **SUMMARY})

    def test_an_unchanged_own_diff_keeps_the_summary_without_codex(self):
        db.put_scope(MONOREPO, 1, {"sha": OLD, "of": OLD, "status": "ready", "summary": SUMMARY, "files": {"a.py": "x"}})
        run, got = self.run_with(0)
        run.assert_not_called()
        self.assertEqual((got["of"], got["summary"]), (HEAD, SUMMARY))

    def test_a_failure_keeps_the_older_summary_and_counts(self):
        db.put_scope(MONOREPO, 1, {"sha": OLD, "of": OLD, "status": "ready", "summary": SUMMARY, "files": {"b.py": "y"}})
        _, got = self.run_with(1, stderr="noise\ncodex judge exited 1: boom")
        self.assertEqual((got["status"], got["errors"], got["error"], got["of"]), ("failed", 1, "codex judge exited 1: boom", OLD))
        self.assertEqual(scope.item(got, HEAD)["verdict"], "focused")
        self.assertEqual(self.run_with(1)[1]["errors"], 2)

    def test_a_usage_limit_does_not_count(self):
        self.assertEqual({k: self.run_with(2, stderr="codex is at its usage limit")[1][k] for k in ("status", "errors")},
                         {"status": "limited", "errors": 0})


class Passes(unittest.TestCase):
    def test_plan_files_leave_the_blind_diff(self):
        diff = "diff --git a/x.py b/x.py\n+x\ndiff --git a/docs/plans/p.md b/docs/plans/p.md\n+p\n"
        self.assertEqual(pr_scope.without_plans(diff), "diff --git a/x.py b/x.py\n+x\n")
        self.assertEqual(pr_scope.numstat("1\t2\tx.py\n-\t-\tlogo.png"),
                         [{"path": "x.py", "additions": 1, "deletions": 2}, {"path": "logo.png", "additions": 0, "deletions": 0}])

    def test_the_merge_puts_the_judge_on_each_change(self):
        blind = {"intent": "i", "touches": [], "changes": [{"kind": "added", "area": "A", "what": "w", "files": ["x.py"]}]}
        judge = {"stated": "s", "verdict": "some-creep", "reason": "r", "scope": [{"index": 0, "in_scope": False, "note": "n"}]}
        merged = pr_scope.merge(blind, judge, ["docs/plans/p.md"])
        self.assertEqual([(c["in_scope"], c["note"]) for c in merged["changes"]], [(False, "n"), (True, "")])
        self.assertEqual(merged["changes"][1]["files"], ["docs/plans/p.md"])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            pr_scope.merge(blind, judge | {"scope": []}, [])
