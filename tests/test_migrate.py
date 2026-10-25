import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pr_wizard import db, names, queue as rq

ROOT = Path(__file__).resolve().parents[1]
MONOREPO, GITOPS = names.MONOREPO, "iprally/gitops"
A, B = "a" * 40, "b" * 40

REVIEWS = {
    "14274": {"sha": A, "status": "baseline", "at": "2026-10-05 13:43:16", "files": {"ui/a.cljs": "1" * 40},
              "verdict": None},
    "17114": {"sha": B, "status": "posted", "verdict": "quality-only", "note": "quality", "rounds": 2, "hold": False,
              "at": "2026-10-24 17:40:00", "files": {"api/b.clj": "2" * 40, "ui/c.cljs": "3" * 40}},
    "17120": {"sha": A, "status": "clean", "verdict": "clean", "note": "no findings", "rounds": 0, "hold": True,
              "at": "2026-10-25 09:00:00", "files": {}},
}
FIXES = {"16956": {"sha": A, "key": f"{A}:12:0:0", "status": "nothing-to-fix", "note": "nothing-to-fix", "errors": 0,
                   "at": "2026-10-22 12:30:22"},
         "17114": {"sha": B, "key": None, "status": "tests-red", "note": "Karma red in x.y-test", "errors": 1,
                   "at": "2026-10-24 18:00:00"}}
GITOPS_FIXES = {"17609": {"sha": B, "key": f"{B}:1:0:0:ci-red-1", "status": "pushed", "note": "pushed bbbb", "errors": 0,
                          "at": "2026-10-22 11:11:00"}}
FIX_STATE = {
    "16614": {"ci_tries": {"build": ["flaky runner"]}, "session": "01a15e03-3062", "handled_reviews": [5598333341],
              "handled_jobs": [42], "reruns": [{"id": 7, "run": 99, "head": A}], "deferred": {"PRRT_1": 2},
              "red": {"head": A, "paths": ["ui/a.cljs"],
                      "result": {"commit_message": "fix: x", "summary": "s", "items": [{"ref": "t1"}]}}},
    "17062": {"ci_tries": {}, "session": "01a15e03-3063", "handled_reviews": [], "handled_jobs": [], "reruns": [],
              "deferred": {}},
}
GITOPS_FIX_STATE = {"17609": {"ci_tries": {}, "session": "01a15e03-3064"}}
CLEAN = {f"17114/{A}": ["opus", "codex"], f"17114/{B}": ["opus", "codex", "quality"]}
NEXT = [17114, 16956]
DEFAULTS = {"note": None, "rounds": 0, "hold": False}

KEPT = (".local/state/review-queue.lock", ".local/state/review-queue.pid", ".local/state/review-queue-gitops.lock",
        ".local/state/pr-fix/pr_fix.py.bak-red")
EPHEMERA = (".local/state/review-queue.json.lock", ".local/state/review-queue.fixes.json.lock",
            ".local/state/review-queue.locks/17114", ".local/state/review-queue.now.d/123.json",
            ".local/state/review-queue-gitops.locks/17609", ".local/state/pr-fix/16614.lock",
            ".local/state/pr-fix/karma.0.lock", ".local/state/pr-fix-gitops/17609.lock")


def layout(home):
    """Today's state of both repos under a temp HOME."""
    state = {".local/state/review-queue.json": REVIEWS, ".local/state/review-queue.fixes.json": FIXES,
             ".local/state/review-queue-gitops.fixes.json": GITOPS_FIXES, ".local/state/review-queue.next": NEXT,
             ".claude/skills/delegator/.clean-reviews.json": CLEAN,
             **{f".local/state/pr-fix/{n}.json": s for n, s in FIX_STATE.items()},
             **{f".local/state/pr-fix-gitops/{n}.json": s for n, s in GITOPS_FIX_STATE.items()}}
    for rel, data in state.items():
        write(home / rel, json.dumps(data, indent=2))
    for rel in KEPT + EPHEMERA:
        write(home / rel, "")
    write(home / ".local/state/pr-fix/16614-jb6nowm_/last.json", "{}")
    return state


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def files(home):
    return {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}


class Migrate(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.wizard = self.home / ".local/state/pr-wizard"
        self.addCleanup(db.close)

    def cli(self, *args, script=ROOT / "bin/pr-wizard", check=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith("IPR_")} | {
            "HOME": str(self.home), "PATH": "/usr/bin:/bin"}
        return subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True, text=True,
                              check=check)

    def rows(self):
        with patch.object(db, "DB", str(self.wizard / "state.db")):
            rows = {"reviews": rq.load(MONOREPO), "fixes": rq.load(MONOREPO, rq.FIXES),
                    "gitops_fixes": rq.load(GITOPS, rq.FIXES), "next": rq.bumped(MONOREPO),
                    "fix_state": db.fix_states(MONOREPO), "gitops_fix_state": db.fix_states(GITOPS),
                    "clean": db.cleared(), "imported_at": db.meta_get("imported_at"),
                    "log": [tuple(r) for r in db.connect().execute("SELECT kind, old_path, new_path FROM migration_log")]}
        db.close()
        return rows

    def legacy_dirs(self):
        return list((self.wizard / "legacy").iterdir())

    def test_the_rows_equal_the_files(self):
        state = layout(self.home)
        out = self.cli("migrate").stdout
        self.assertIn(f"{MONOREPO:<16} reviews 3  fixes 2  fix_state 2  clean_reviews 5  next 2", out)
        self.assertIn(f"{GITOPS:<16} reviews 0  fixes 1  fix_state 1  clean_reviews 0  next 0", out)
        rows = self.rows()
        self.assertEqual(rows["reviews"], {n: DEFAULTS | e for n, e in REVIEWS.items()})
        self.assertEqual((rows["fixes"], rows["gitops_fixes"], rows["next"]), (FIXES, GITOPS_FIXES, NEXT))
        self.assertEqual(rows["fix_state"], {int(n): s for n, s in FIX_STATE.items()})
        self.assertEqual(rows["gitops_fix_state"], {int(n): s for n, s in GITOPS_FIX_STATE.items()})
        self.assertEqual(rows["clean"], {(MONOREPO, 17114, A): ["opus", "codex"],
                                         (MONOREPO, 17114, B): ["opus", "codex", "quality"]})
        self.assertRegex(rows["imported_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

        legacy, = self.legacy_dirs()
        self.assertRegex(legacy.name, r"^\d{14}$")
        after = files(self.home)
        for rel, data in state.items():
            self.assertNotIn(rel, after)
            self.assertEqual(json.loads(after[f"{legacy.relative_to(self.home)}/{rel}"]), data)
        self.assertIn(".local/state/pr-wizard/scratch/16614-jb6nowm_/last.json", after)
        for rel in KEPT:
            self.assertIn(rel, after)
        for rel in EPHEMERA:
            self.assertFalse((self.home / rel).exists(), rel)
        self.assertFalse((self.home / ".local/state/pr-fix-gitops").exists())
        kinds = [kind for kind, *_ in rows["log"]]
        self.assertEqual((kinds.count("imported"), kinds.count("scratch"), kinds.count("deleted")),
                         (len(state), 1, len(EPHEMERA)))

    def test_a_dry_run_prints_the_counts_and_changes_nothing(self):
        layout(self.home)
        before = files(self.home)
        out = self.cli("migrate", "-n").stdout
        self.assertIn(f"would import:\n  {MONOREPO:<16} reviews 3  fixes 2", out)
        self.assertIn("8 files to legacy/, 1 scratch dirs to scratch/, 8 locks and live-run files deleted", out)
        self.assertEqual(files(self.home), before)
        self.assertFalse(self.wizard.exists())

    def test_a_second_run_is_a_no_op(self):
        layout(self.home)
        self.cli("migrate")
        first = self.rows()
        write(self.home / ".local/state/review-queue.json", json.dumps({"1": REVIEWS["17114"]}))
        self.assertIn("already holds", self.cli("migrate").stdout)
        self.assertIn("already holds", self.cli("migrate", "-n").stdout)
        self.assertEqual(self.rows(), first)
        self.assertEqual(len(self.legacy_dirs()), 1)

    def test_two_processes_migrate_at_once(self):
        layout(self.home)
        env = {**os.environ, "HOME": str(self.home)}
        runs = [subprocess.Popen([sys.executable, str(ROOT / "bin/pr-wizard"), "migrate"], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outs = [run.communicate() + (run.returncode,) for run in runs]
        self.assertEqual([rc for *_, rc in outs], [0, 0], outs)
        self.assertEqual(sorted("imported:" in out for out, *_ in outs), [False, True])
        self.assertEqual(len(self.legacy_dirs()), 1)
        self.assertEqual(sum(map(len, self.rows()["clean"].values())), 5)

    def test_reverse_exports_the_db_with_the_later_changes(self):
        state = layout(self.home)
        self.cli("migrate")
        later = {"sha": A, "key": f"{A}:3:1:1", "status": "pushed", "note": "pushed aaaa", "errors": 0,
                 "at": "2026-10-26 10:00:00"}
        with patch.object(db, "DB", str(self.wizard / "state.db")):
            rq.record(MONOREPO, "17120", later, rq.FIXES)
            rq.save_bumped(MONOREPO, [17120, 17114])
            db.add_clean(MONOREPO, 17120, A, "opus")
            db.put_fix_state(GITOPS, 17609, {"session": "s4", "ci_tries": {"lint": ["x"]}})
        db.close()
        self.cli("migrate", "--reverse")
        expected = {**state, ".local/state/review-queue.json": {n: DEFAULTS | e for n, e in REVIEWS.items()},
                    ".local/state/review-queue.fixes.json": FIXES | {"17120": later},
                    ".local/state/review-queue.next": [17120, 17114],
                    ".claude/skills/delegator/.clean-reviews.json": CLEAN | {f"17120/{A}": ["opus"]},
                    ".local/state/pr-fix-gitops/17609.json": {"session": "s4", "ci_tries": {"lint": ["x"]}},
                    ".local/state/review-queue-gitops.json": {}, ".local/state/review-queue-gitops.next": []}
        for rel, data in expected.items():
            self.assertEqual(json.loads((self.home / rel).read_text()), data, rel)
        self.assertEqual((self.home / ".local/state/review-queue.next").read_text(), "[17120, 17114]")
        self.assertTrue((self.home / ".local/state/review-queue.json").read_text().startswith('{\n  "14274": {\n'))
        self.assertFalse((self.wizard / "state.db").exists())
        self.assertEqual(len(list(self.wizard.glob("state.db.reverted-*"))), 1)
        self.assertEqual(len(self.legacy_dirs()), 1)

    def test_reverse_needs_a_db(self):
        layout(self.home)
        before = files(self.home)
        self.assertIn("no ", self.cli("migrate", "--reverse", check=False).stderr)
        self.assertEqual(files(self.home), before)

    def test_a_script_that_starts_first_migrates_first(self):
        for script, cmd in (("pr_review.py", "scope"), ("pr_fix.py", "dump")):
            with self.subTest(script):
                layout(self.home)
                run = self.cli(cmd, "--pr", "17114", script=ROOT / "review" / script, check=False)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(self.rows()["fixes"], FIXES)
                self.assertFalse((self.home / ".local/state/review-queue.fixes.json").exists())
                for p in self.home.iterdir():
                    subprocess.run(["rm", "-rf", str(p)], check=True)


class QueueOnTheDb(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(db, "DB", f"{temp.name}/state.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db.close)

    def test_record_and_load_keep_the_dicts(self):
        rq.record(MONOREPO, "17114", REVIEWS["17114"])
        rq.record(GITOPS, "17609", GITOPS_FIXES["17609"], rq.FIXES)
        self.assertEqual(rq.load(MONOREPO), {"17114": REVIEWS["17114"]})
        self.assertEqual((rq.load(GITOPS), rq.load(GITOPS, rq.FIXES)), ({}, GITOPS_FIXES))

    def test_save_bumped_sets_the_order(self):
        rq.save_bumped(MONOREPO, [3, 1, 2])
        rq.save_bumped(MONOREPO, [x for x in rq.bumped(MONOREPO) if x != 1])
        rq.save_bumped(GITOPS, [1])
        self.assertEqual((rq.bumped(MONOREPO), rq.bumped(GITOPS)), ([3, 2], [1]))

    def test_live_runs_show_their_lane_and_start(self):
        rq.in_review(MONOREPO, 5, True, "fix")
        rq.in_review(MONOREPO, 6, True)
        self.assertEqual({n: re.sub(r"\d", "0", v) for n, v in rq.reviewing(MONOREPO).items()},
                         {5: "fix 00:00:00", 6: "review 00:00:00"})
        rq.in_review(MONOREPO, 5, False)
        self.assertEqual(list(rq.reviewing(MONOREPO)), [6])
        self.assertEqual(rq.reviewing(GITOPS), {})


if __name__ == "__main__":
    unittest.main()
