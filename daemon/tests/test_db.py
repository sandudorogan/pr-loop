import multiprocessing
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from unittest import mock

import prs  # noqa: F401
from pr_wizard import db

R, G = "iprally/iprally", "iprally/gitops"
SHA, SHA2 = "a" * 40, "b" * 40
OLD = "2020-01-01T00:00:00+00:00"


def write_many(path, repo, start, count):
    db.DB = path
    for n in range(start, start + count):
        db.put_review(repo, n, {"sha": SHA, "status": "posted"})
        db.bump(repo, n)
    db.close()


class DbCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "state", "state.db")
        patch = mock.patch.object(db, "DB", self.path)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(db.close)
        db.close()

    def sql(self, query, *args):
        with closing(sqlite3.connect(self.path)) as c, c:
            return c.execute(query, args).fetchall()


class Connection(DbCase):
    def test_pragmas_and_schema(self):
        c = db.connect()
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(c.execute("PRAGMA busy_timeout").fetchone()[0], 10_000)
        self.assertEqual(c.execute("PRAGMA synchronous").fetchone()[0], 1)
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(len(db.meta_get("events_epoch")), 6)

    def test_upgrade_from_version_one_adds_paused_prs(self):
        os.makedirs(os.path.dirname(self.path))
        self.sql("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.sql("PRAGMA user_version = 1")
        db.pause_pr(R, 1, True)
        self.assertEqual((list(db.paused_prs()), self.sql("PRAGMA user_version")), ([(R, 1)], [(2,)]))
        db.pause_pr(R, 1, False)
        self.assertEqual(db.paused_prs(), {})

    def test_upgrade_from_version_zero_keeps_data(self):
        os.makedirs(os.path.dirname(self.path))
        self.sql("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.sql("INSERT INTO meta VALUES ('imported_at', 'x')")
        self.assertEqual(db.meta_get("imported_at"), "x")
        self.assertEqual(self.sql("PRAGMA user_version"), [(2,)])
        self.assertEqual(db.review(R, 1), {})
        db.close()
        self.assertEqual(db.meta_get("imported_at"), "x")

    def test_connection_is_per_thread(self):
        seen = []
        t = threading.Thread(target=lambda: (seen.append(db.connect()), db.close()))
        t.start()
        t.join()
        self.assertIsNot(seen[0], db.connect())

    def test_tx_rolls_back_and_nests(self):
        with self.assertRaises(ValueError), db.tx():
            db.meta_set("a", 1)
            raise ValueError
        self.assertIsNone(db.meta_get("a"))
        with db.tx():
            db.meta_set("a", 1)
            db.meta_set("b", 2)
        self.assertEqual((db.meta_get("a"), db.meta_get("b")), ("1", "2"))

    def test_data_version_moves_on_a_commit_by_another_connection(self):
        before = db.data_version()
        t = threading.Thread(target=lambda: (db.meta_set("k", "v"), db.close()))
        t.start()
        t.join()
        self.assertNotEqual(db.data_version(), before)


class Concurrency(DbCase):
    def test_two_processes_write_at_once(self):
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=write_many, args=(self.path, repo, 1, 40)) for repo in (R, G)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(self.sql("SELECT repo, count(*) FROM reviews GROUP BY repo ORDER BY repo"), [(G, 40), (R, 40)])
        self.assertEqual(db.next_list(R), list(range(1, 41))[::-1])

    def test_reader_sees_the_old_snapshot_during_a_write(self):
        db.put_review(R, 1, {"sha": SHA, "status": "clean"})
        seen, inside, done = [], threading.Event(), threading.Event()

        def reader():
            inside.wait()
            seen.append(db.review(R, 1)["status"])
            db.close()
            done.set()

        t = threading.Thread(target=reader)
        t.start()
        with db.tx():
            db.put_review(R, 1, {"sha": SHA2, "status": "posted"})
            inside.set()
            self.assertTrue(done.wait(5))
        t.join()
        self.assertEqual((seen, db.review(R, 1)["status"]), (["clean"], "posted"))


class Rows(DbCase):
    def test_review_roundtrip(self):
        entry = {"sha": SHA, "status": "posted", "verdict": "quality-only", "note": "quality", "rounds": 2,
                 "hold": True, "at": "2026-10-05 13:43:16", "files": {"a/b.clj": "c0ffee"}}
        db.put_review(R, 7, entry)
        self.assertEqual(db.review(R, "7"), entry)
        self.assertEqual(db.review(G, 7), {})

    def test_review_defaults_match_a_legacy_baseline_entry(self):
        db.put_review(R, 1, {"sha": SHA, "status": "baseline", "at": OLD})
        self.assertEqual(db.review(R, 1), {"sha": SHA, "status": "baseline", "verdict": None, "note": None,
                                           "rounds": 0, "hold": False, "at": OLD, "files": {}})

    def test_fix_roundtrip(self):
        entry = {"sha": SHA, "key": f"{SHA}:12:0:0", "status": "tests-red", "note": "Karma red", "errors": 3,
                 "at": "2026-10-22 12:30:22"}
        db.put_fix(R, 7, entry)
        self.assertEqual(db.fix(R, 7), entry)
        db.put_fix(R, 7, entry | {"key": None, "gate": {"name": "Karma"}})
        self.assertEqual(db.fix(R, 7), entry | {"key": None, "gate": {"name": "Karma"}})

    def test_fix_state_roundtrip_keeps_only_saved_keys(self):
        state = {"session": "01a1", "handled_reviews": [5575901991], "handled_jobs": [], "deferred": {"T1": 2},
                 "ci_tries": {"build": [1, 2]}, "reruns": [{"head": SHA}],
                 "red": {"head": SHA, "paths": ["a.cljs"], "result": {"summary": "x"}}}
        db.put_fix_state(R, 7, state)
        self.assertEqual(db.fix_state(R, 7), state)
        db.put_fix_state(R, 7, {"handled_reviews": [1]})
        self.assertEqual(db.fix_state(R, 7), {"handled_reviews": [1]})
        self.assertEqual(db.fix_state(R, 8), {})

    def test_reviewer_results_keep_the_latest_head_only(self):
        digest = {"counts": {"high": 1}, "top": [{"title": "t"}]}
        db.put_reviewer_result(R, 7, SHA, "opus", {"result": "posted", "engine": "claude", "round": 1, "digest": digest,
                                                   "conventions": ["AGENTS.md"], "url": "u", "at": OLD})
        db.put_reviewer_result(R, 7, SHA, "codex", {"result": "clean"})
        self.assertEqual(set(db.reviewer_results(R, 7)), {"opus", "codex"})
        self.assertEqual(db.reviewer_results(R, 7)["opus"]["digest"], digest)
        self.assertEqual(db.reviewer_results(R, 7)["opus"]["conventions"], ["AGENTS.md"])
        db.put_reviewer_result(R, 7, SHA2, "opus", {"result": "clean"})
        self.assertEqual({v["sha"] for v in db.reviewer_results(R, 7).values()}, {SHA2})
        db.put_reviewer_result(R, 8, SHA, "opus", {"result": "clean"})
        self.assertEqual(len(db.reviewer_results(R, 8)), 1)

    def test_clean_keeps_order_and_trims_after_30_days(self):
        for who in ("opus", "codex", "opus"):
            db.add_clean(R, 7, SHA, who)
        self.assertEqual(db.clean(R, 7, SHA), ["opus", "codex"])
        self.assertEqual(db.clean(G, 7, SHA), [])
        self.sql("INSERT INTO clean_reviews VALUES (?, 1, ?, 'opus', ?)", R, SHA, OLD)
        self.assertEqual(db.clean(R, 1, SHA), ["opus"])
        db.add_clean(R, 7, SHA, "quality")
        self.assertEqual(db.clean(R, 1, SHA), [])

    def test_next_bumps_to_the_front_and_moves_repeats(self):
        db.bump(R, 1)
        db.bump(R, 2, 3)
        db.bump(G, 1)
        self.assertEqual(db.next_list(R), [2, 3, 1])
        db.bump(R, 1)
        self.assertEqual(db.next_list(R), [1, 2, 3])
        db.drop_next(R, 2)
        self.assertEqual((db.next_list(R), db.next_list(G)), ([1, 3], [1]))

    def test_pr_override_keeps_created_at(self):
        self.assertIsNone(db.pr_override(R, 7))
        db.put_pr_override(R, 7, {"review": {"enabled": False}})
        first = db.pr_override(R, 7)
        self.sql("UPDATE pr_overrides SET created_at = ?", OLD)
        db.put_pr_override(R, 7, {"fix": {"enabled": False}})
        row = db.pr_override(R, 7)
        self.assertEqual((first["config"], row["config"], row["created_at"]),
                         ({"review": {"enabled": False}}, {"fix": {"enabled": False}}, OLD))
        db.drop_pr_override(R, 7)
        self.assertIsNone(db.pr_override(R, 7))

    def test_meta(self):
        self.assertEqual(db.meta_get("paused", "0"), "0")
        db.meta_set("paused", 1)
        self.assertEqual(db.meta_get("paused"), "1")


class Runs(DbCase):
    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def test_dead_pid_runs_are_ignored_and_swept(self):
        db.run_start(R, 1, "review", reviewers=[{"id": "opus", "state": "running"}])
        db.run_start(R, 2, "fix", pid=self.dead_pid())
        db.run_start(G, 3, "fix")
        live = db.live_runs(R)
        self.assertEqual(list(live), [1])
        self.assertEqual(live[1]["reviewers"], [{"id": "opus", "state": "running"}])
        self.assertEqual(set(db.live_runs()), {(R, 1), (G, 3)})
        db.sweep_runs()
        self.assertEqual(self.sql("SELECT number FROM runs ORDER BY number"), [(1,), (3,)])

    def test_update_and_end(self):
        db.run_start(R, 1, "review")
        db.run_update(R, 1, [{"id": "opus", "state": "posted"}])
        self.assertEqual(db.live_runs(R)[1]["reviewers"], [{"id": "opus", "state": "posted"}])
        db.run_end(R, 1)
        self.assertEqual(db.live_runs(R), {})


class Events(DbCase):
    def add(self, n, type="ready_for_approval", head=SHA):
        return db.add_event(type, R, n, f"t{n}", f"https://x/{n}", "colleague", head, "clean")

    def test_event_shape_and_stable_id(self):
        e = self.add(5)
        self.assertEqual(e["id"], f"ready_for_approval:{R}#5@{SHA[:12]}")
        self.assertEqual((e["key"], e["seq"], e["verdict"]), (f"{R}#5", 1, "clean"))
        again = self.add(5)
        self.assertEqual((again["id"], again["seq"]), (e["id"], 2))
        self.assertEqual(len(db.events_after("x.0")["events"]), 1)

    def test_cursor_rules(self):
        fresh = db.events_after()
        self.assertEqual((fresh["events"], fresh["reset"]), ([], False))
        epoch = fresh["cursor"].split(".")[0]
        for n in (1, 2, 3):
            self.add(n)
        got = db.events_after(f"{epoch}.1")
        self.assertEqual(([e["number"] for e in got["events"]], got["reset"], got["cursor"]), ([2, 3], False, f"{epoch}.3"))
        self.assertEqual(db.events_after(f"{epoch}.3")["events"], [])
        other = db.events_after("zzzzzz.2")
        self.assertEqual(([e["number"] for e in other["events"]], other["reset"]), ([1, 2, 3], True))

    def test_trims_to_the_last_rows_and_resets_a_stale_cursor(self):
        epoch = db.meta_get("events_epoch")
        with mock.patch.object(db, "EVENTS_KEEP", 3):
            for n in range(1, 8):
                self.add(n)
        got = db.events_after(f"{epoch}.1")
        self.assertEqual(([e["number"] for e in got["events"]], got["reset"]), ([5, 6, 7], True))
        self.assertEqual(db.events_after(f"{epoch}.4")["reset"], False)
        self.assertEqual(db.events_after(f"{epoch}.7")["events"], [])


class History(DbCase):
    def test_upsert_merges_and_orders(self):
        db.upsert_history(R, 1, title="one", url="u1", author="me", mine=True, outcome="posted", head=SHA, at="2026-10-24T10:00:00+03:00")
        db.upsert_history(R, 2, title="two", at="2026-10-25T10:00:00+03:00")
        db.upsert_history(R, 1, outcome="pushed", fixes_pushed=1, at="2026-10-25T11:00:00+03:00")
        got = db.history()
        self.assertEqual([h["number"] for h in got], [1, 2])
        self.assertEqual(got[0], {"key": f"{R}#1", "repo": R, "number": 1, "title": "one", "url": "u1", "author": "me",
                                  "mine": True, "outcome": "pushed", "rounds": 0, "fixes_pushed": 1, "head": SHA,
                                  "first_at": "2026-10-24T10:00:00+03:00", "at": "2026-10-25T11:00:00+03:00",
                                  "closed_at": None, "state": "open"})
        db.upsert_history(G, 3, title="g")
        self.assertEqual([h["number"] for h in db.history(repo=G)], [3])
        self.assertEqual(len(db.history(limit=2)), 2)

    def test_trims_by_count_and_by_age(self):
        db.upsert_history(R, 99, title="old", at=OLD)
        with mock.patch.object(db, "HISTORY_KEEP", 3):
            for n in range(1, 6):
                db.upsert_history(R, n, title=str(n), at=f"2026-10-2{n}T10:00:00+03:00")
        self.assertEqual([h["number"] for h in db.history()], [5, 4, 3])

    def test_every_column_survives(self):
        fields = {"title": "t", "url": "u", "author": "a", "mine": False, "outcome": "approved", "rounds": 3,
                  "fixes_pushed": 2, "head": SHA, "first_at": "2026-10-23T09:12:00+03:00",
                  "at": "2026-10-24T15:40:00+03:00", "closed_at": "2026-10-24T16:05:00+03:00", "state": "merged"}
        db.upsert_history(R, 4, **fields)
        self.assertEqual(db.history()[0], {"key": f"{R}#4", "repo": R, "number": 4, **fields})


if __name__ == "__main__":
    unittest.main()
