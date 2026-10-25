import json
import os
import sqlite3
import tempfile
import threading
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from prs import GITOPS, HEAD, MONOREPO, pr, rq
from pr_wizard import config, db, snapshot

NEW = "acme/widgets"
OTHER = "b" * 40


class Configured(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "config.json")
        env = patch.dict(os.environ, {"PR_WIZARD_CONFIG": self.path})
        env.start()
        self.addCleanup(env.stop)
        patcher = patch.object(db, "DB", os.path.join(self.dir.name, "state.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db.close)

    def write(self, doc):
        with open(self.path, "w") as fh:
            json.dump(doc, fh)
        self.assertIsNone(rq.SETTINGS.get().error)


def reviewer(rid, **kw):
    return next(dict(r, **kw) for r in config.DEFAULTS["review"]["reviewers"] if r["id"] == rid)


class Resize(unittest.TestCase):
    def test_a_larger_pool_starts_workers_and_a_smaller_one_retires_them_after_their_pass(self):
        running, release = threading.Semaphore(0), threading.Event()
        pending = rq.Pending([pr(1), pr(2)])
        spawn = lambda: rq.worker(pending, True, lambda *_: running.release() or release.wait(5))
        with patch.object(rq, "bumps", return_value={MONOREPO: []}):
            threads = pending.resize(2, spawn) + pending.resize(2, spawn)
            self.assertEqual(len(threads), 2)
            self.assertTrue(running.acquire(timeout=5) and running.acquire(timeout=5))
            self.assertEqual(pending.resize(1, spawn), [])
            self.assertEqual(len(pending.busy), 2)
            release.set()
            threads[0].join(1), threads[1].join(1)
            self.assertEqual(([t.is_alive() for t in threads].count(True), pending.live), (1, 1))
            pending.resize(0, spawn)
            [t.join(5) for t in threads]
        self.assertEqual(pending.live, 0)

    def test_a_worker_that_waits_retires_at_once(self):
        pending = rq.Pending(workers=0)
        threads = pending.resize(2, lambda: rq.worker(pending, True, lambda *_: None))
        pending.resize(0, list)
        for t in threads:
            t.join(5)
            self.assertFalse(t.is_alive())
        self.assertEqual(pending.live, 0)

    def test_a_worker_survives_a_failing_take_and_gives_its_slot_back(self):
        pending = rq.Pending([pr(1)])
        ran = threading.Event()
        calls = iter([sqlite3.OperationalError("database is locked")])

        def bumps():
            if err := next(calls, None):
                raise err
            return {MONOREPO: []}

        with patch.object(rq, "bumps", bumps), patch.object(rq.time, "sleep"):
            threads = pending.resize(1, lambda: rq.worker(pending, False, lambda *_: ran.set()))
            threads[0].join(5)
        self.assertTrue(ran.is_set())
        self.assertEqual(pending.live, 0)


class Live(Configured):
    def test_the_daemon_resizes_its_pools_when_the_file_changes(self):
        rt, review, fixes = rq.Runtime(), rq.Pending(), rq.Pending()
        with patch.object(rq, "worker", return_value=None) as spawned:
            rt.resize(review, fixes)
            self.assertEqual((review.workers, fixes.workers, spawned.call_count), (3, 3, 6))
            self.write({"review": {"workers": 5}, "fix": {"workers": 1}})
            rt.resize(review, fixes)
        self.assertEqual((review.workers, fixes.workers, spawned.call_count), (5, 1, 8))
        self.assertEqual(rt.info()["refresh"]["interval_s"], 300)

    def test_a_save_beside_a_symlink_is_seen(self):
        real = os.path.join(self.dir.name, "real.json")
        with open(real, "w") as fh:
            json.dump({"refresh": {"interval_s": 600, "idle_s": 30}}, fh)
        os.symlink(real, self.path)
        self.assertEqual(rq.cfg()["refresh"]["interval_s"], 600)
        config.save(config.merge(rq.cfg(), {"refresh": {"interval_s": 900}}), self.path)
        self.assertEqual(rq.cfg()["refresh"]["interval_s"], 900)


class Projects(Configured):
    def test_defaults_serve_both_repos_with_their_lanes(self):
        self.assertEqual(list(rq.projects()), [MONOREPO, GITOPS])
        self.assertEqual((rq.lanes(MONOREPO), rq.lanes(GITOPS)), ("review+fix", "fix"))

    def test_a_config_project_needs_a_root_else_it_is_skipped_with_a_log_line(self):
        self.write({"projects": {NEW: {"review": {"rounds": 2}}, "acme/tools": {"root": "~/src/tools"},
                                 MONOREPO: {"root": "/src/iprally"}}})
        with patch.object(rq, "log") as log:
            rq.unrooted()
        self.assertEqual(rq.projects(), {MONOREPO: "/src/iprally", GITOPS: os.path.expanduser("~/workdir/gitops"),
                                 "acme/tools": os.path.expanduser("~/src/tools")})
        log.assert_called_once_with(NEW, "-", f"skipped: no checkout, set projects[{NEW}].root in the config")
        self.assertEqual(rq.child("acme/tools")["env"]["IPR_REPO_ROOT"], os.path.expanduser("~/src/tools"))

    def test_the_query_scopes_every_project(self):
        self.write({"projects": {NEW: {"root": "/src/widgets"}}})
        with patch.object(rq, "sh", return_value=json.dumps({"data": {s: {"nodes": []} for s in
                                                                      ("mine", "requested", "reviewed")}})) as sh:
            rq.queue()
        self.assertIn(f"mine=repo:{MONOREPO} repo:{GITOPS} repo:{NEW} is:pr is:open author:@me", sh.call_args.args)

    def test_lanes_follow_the_project_and_the_labels_still_win(self):
        self.write({"projects": {NEW: {"root": "/src/w", "fix": {"enabled": False}}, GITOPS: {"review": {"enabled": True}}}})
        self.assertFalse(rq.unreviewed(pr(repo=GITOPS)))
        self.assertTrue(rq.unreviewed(pr(repo=GITOPS, labels=[rq.NO_REVIEW])))
        self.assertFalse(rq.fixable(pr(repo=NEW), {}, {}))
        self.assertFalse(rq.fixing(pr(repo=NEW), {"1": {"status": "posted"}}, {}))
        seen = {"sha": HEAD, "status": "posted", "verdict": "posted", "at": "2026-10-25 10:00:00"}
        self.assertEqual(rq.row(pr(repo=NEW), seen, {}, []), (4, "posted", "fix lane off"))
        self.assertEqual(rq.lanes(NEW), "review")

    def test_the_snapshot_reports_projects_and_pools_from_the_config(self):
        self.write({"review": {"workers": 2}, "projects": {NEW: {"root": "/src/w", "review": {"enabled": False}}}})
        snap = snapshot.build([], snapshot.read(), {"generated_at": None, "fetched_at": None, "paused": False,
                                                    "refresh": {}})
        self.assertEqual([(p["repo"], p["review"], p["checkout"]["path"]) for p in snap["projects"]][2],
                         (NEW, False, "/src/w"))
        self.assertEqual([p["workers"] for p in snap["lanes"]["pools"]], [2, 3])


class Gates(Configured):
    seen = {"files": {"a.py": "1"}}

    def test_rounds_added_lines_and_trivial_files_come_from_the_project(self):
        self.write({"projects": {NEW: {"root": "/src/w", "review": {"rounds": 2, "max_added": 10,
                                                                   "trivial": ["*.txt"]}}}})
        files = {"a.py": "2"}
        self.assertEqual(rq.decide(pr(repo=NEW), {"rounds": 2, **self.seen}, files, False),
                         ("needs-human", "2 rounds in a row with findings, review it by hand or run --pr 1"))
        self.assertIsNone(rq.decide(pr(), {"rounds": 2, **self.seen}, files, False))
        self.assertEqual(rq.decide(pr(repo=NEW, additions=11), {}, {}, False)[0], "too-big")
        self.assertEqual(rq.decide(pr(repo=NEW), {"files": {"n.txt": "1"}}, {}, False)[0], "trivial")
        self.assertIsNone(rq.decide(pr(repo=NEW), {"files": {"n.md": "1"}}, {}, False))

    def test_fix_pass_timeout_and_max_errors_come_from_the_project(self):
        self.write({"projects": {NEW: {"root": "/src/w", "fix": {"pass_timeout_s": 600, "max_errors": 1}}}})
        out = CompletedProcess([], 1, "", "boom")
        with patch.object(rq.subprocess, "run", return_value=out) as run, patch.object(rq, "log"), \
                patch.object(rq, "in_review"):
            rq.fix(pr(repo=NEW), [])
        self.assertEqual(run.call_args.kwargs["timeout"], 600)
        self.assertEqual(rq.load(NEW, rq.FIXES)["1"]["key"], rq.feedback_key(pr(repo=NEW)))


class Reviewers(Configured):
    def test_only_enabled_reviewers_run_and_skipped_ones_count_as_stopped(self):
        self.write({"review": {"reviewers": [reviewer("opus"), reviewer("codex", enabled=False), reviewer("quality")]}})
        ran = []
        outputs = {"opus": {"stop": True, "reason": "no-findings"},
                   "quality": {"posted": False, "stop": True, "reason": "no-conventions", "conventions": []}}
        with patch.object(rq, "run_reviewer", side_effect=lambda repo, n, r: ran.append(r) or outputs[r]):
            self.assertEqual(rq.review(MONOREPO, 5, HEAD), ("clean", "no findings"))
        self.assertEqual(sorted(ran), ["opus", "quality"])

    def test_no_enabled_reviewer_skips_instead_of_raising(self):
        self.write({"review": {"enabled": False, "reviewers": [reviewer(r, enabled=False) for r in ("opus", "codex", "quality")]}})
        with patch.object(rq, "run_reviewer") as run:
            self.assertEqual(rq.review(MONOREPO, 5, HEAD), ("skipped", "no reviewer enabled"))
        run.assert_not_called()

    def test_one_engine_at_its_limit_is_limited(self):
        out = CompletedProcess([], 1, "", "error: codex is at its usage limit\n")
        db.run_start(MONOREPO, 5, "review", reviewers=[])
        with patch.object(rq.subprocess, "run", return_value=out), patch.object(rq, "log") as log:
            self.assertIs(rq.run_reviewer(MONOREPO, 5, "codex"), rq.LIMITED)
        log.assert_called_with(MONOREPO, 5, "codex stopped: codex is at its usage limit")


class Verdict(Configured):
    def handle(self, outcome):
        recorded = []
        seen = {"sha": OTHER, "status": "posted", "verdict": "posted", "rounds": 1, "hold": False,
                "at": "2026-10-25 09:00:00", "files": {"a.py": "1"}}
        with patch.object(rq, "load", return_value={"1": seen}), patch.object(rq, "fingerprint", return_value={"a.py": "2"}), \
                patch.object(rq, "review", return_value=outcome), \
                patch.object(rq, "record", side_effect=lambda repo, key, entry, kind=rq.STATE: recorded.append(entry)), \
                patch.object(rq, "post_clean_notice"), patch.object(rq, "ready_alert"), patch.object(rq, "drop_ready_alert"), \
                patch.object(rq, "in_review"), patch.object(rq, "kick"), patch.object(rq, "announce"), \
                patch.object(rq, "log_once"), patch.object(rq, "log"):
            rq.handle(pr(mine=False, requested=True), [], None, False)
        return recorded[0]["verdict"]

    def test_findings_of_advisory_reviewers_alone_are_quality_only(self):
        self.write({"review": {"reviewers": [reviewer("opus", advisory=True), reviewer("codex"),
                                             reviewer("quality", advisory=False)]}})
        self.assertEqual(self.handle(("posted", "opus")), "quality-only")
        self.assertEqual(self.handle(("posted", "quality")), "posted")
        self.assertEqual(self.handle(("posted", "opus, codex")), "posted")

    def test_a_raising_review_still_ends_the_run_row(self):
        seen = {"sha": OTHER, "status": "posted", "verdict": "posted", "rounds": 1, "hold": False,
                "at": "2026-10-25 09:00:00", "files": {"a.py": "1"}}
        with patch.object(rq, "load", return_value={"1": seen}), patch.object(rq, "fingerprint", return_value={"a.py": "2"}), \
                patch.object(rq, "review", side_effect=RuntimeError("boom")), patch.object(rq, "drop_ready_alert"), \
                patch.object(rq, "announce"), patch.object(rq, "in_review") as in_review, \
                patch.object(rq, "log_once"), patch.object(rq, "log"):
            with self.assertRaises(RuntimeError):
                rq.handle(pr(mine=False, requested=True), [], None, False)
        self.assertEqual([c.args for c in in_review.call_args_list], [(MONOREPO, 1, True), (MONOREPO, 1, False)])


class FixNote(Configured):
    def test_a_red_gate_names_itself(self):
        res = {"status": "tests-red", "gate": "pytest", "failing": ["tests/test_a.py"], "worktree": "/wt"}
        self.assertEqual(rq.fix_note(res, "", NEW), "pytest red in tests/test_a.py — /wt")

    def test_without_a_gate_key_it_names_the_projects_test_gates(self):
        gate = {"name": "go test", "kind": "test", "when": ["*.go"], "run": "go test ./..."}
        self.write({"projects": {NEW: {"root": "/src/w", "fix": {"gates": [gate]}}}})
        res = {"status": "tests-red", "failing": ["pkg"], "worktree": "/wt"}
        self.assertEqual(rq.fix_note(res, "", NEW), "go test red in pkg — /wt")


if __name__ == "__main__":
    unittest.main()
