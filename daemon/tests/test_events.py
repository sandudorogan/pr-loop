import os
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from prs import HEAD, MONOREPO, pr, rq
from test_api_read import call, fixture, shape
from pr_loop import api, db

OTHER = "b" * 40
READY_SEEN = {"sha": OTHER, "status": "clean", "verdict": "clean", "note": "no findings", "rounds": 0, "hold": False,
              "at": "2026-10-25 10:00:00", "files": {"a.py": "1"}}


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])
        patcher = patch.object(db, "DB", os.path.join(self.dir, "state.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db.close)
        db.close()

    def events(self):
        return db.events_after("x.0")["events"]


class Handle(Store):
    """handle() records the events of api.md §3.3 for UIs to notify from."""

    def handle(self, p, outcome, seen=None, only=False):
        seen = READY_SEEN if seen is None else seen
        with patch.object(rq, "load", return_value={str(p["number"]): seen}), \
                patch.object(rq, "fingerprint", return_value={"a.py": "2"}), \
                patch.object(rq, "review", return_value=outcome), patch.object(rq, "record"), \
                patch.object(rq, "post_clean_notice"), patch.object(rq, "in_review"), patch.object(rq, "kick"), \
                patch.object(rq, "save_bumped"), patch.object(rq, "bumped", return_value=[]), \
                patch.object(rq, "log_once"), patch.object(rq, "log"):
            rq.handle(p, [], only, False)

    def test_a_clean_colleague_pr_is_ready_for_approval(self):
        self.handle(pr(mine=False, requested=True), ("clean", "no findings"), seen={})
        (e,) = self.events()
        self.assertEqual((e["type"], e["key"], e["verdict"], e["author"], e["head"], e["title"]),
                         ("ready_for_approval", f"{MONOREPO}#1", "clean", "colleague", HEAD, "title 1"))
        self.assertEqual(e["url"], f"https://github.com/{MONOREPO}/pull/1")
        self.assertEqual(shape(e, fixture("events")["events"][0]), [])

    def test_quality_notes_only_are_ready_too(self):
        self.handle(pr(mine=False, requested=True), ("posted", "quality"), seen={})
        self.assertEqual([e["verdict"] for e in self.events()], ["quality-only"])

    def test_findings_and_my_own_prs_emit_nothing(self):
        self.handle(pr(mine=False, requested=True), ("posted", "opus, codex"), seen={})
        self.handle(pr(2, mine=True), ("clean", "no findings"), seen={})
        self.handle(pr(3, mine=True), ("posted", "quality"), seen={})
        self.handle(pr(4, mine=False, requested=True), ("failed", "opus failed 3×"), seen={})
        self.assertEqual(self.events(), [])

    def test_the_same_head_made_ready_twice_is_one_event(self):
        for _ in range(2):
            self.handle(pr(mine=False, requested=True), ("clean", "no findings"), seen={}, only=True)
        (e,) = self.events()
        self.assertEqual((e["id"], e["seq"]), (f"ready_for_approval:{MONOREPO}#1@{HEAD[:12]}", 2))

    def test_a_new_head_on_a_ready_colleague_pr_withdraws_it(self):
        self.handle(pr(mine=False, requested=True), ("posted", "opus"))
        withdrawn, = [e for e in self.events() if e["type"] == "ready_withdrawn"]
        self.assertEqual((withdrawn["id"], withdrawn["verdict"], withdrawn["head"], withdrawn["key"]),
                         (f"ready_withdrawn:{MONOREPO}#1@{HEAD[:12]}", None, HEAD, f"{MONOREPO}#1"))
        self.assertEqual(shape(withdrawn, fixture("events")["events"][1]), [])

    def test_a_withdrawal_and_the_next_ready_come_in_order(self):
        self.handle(pr(mine=False, requested=True), ("clean", "no findings"))
        self.assertEqual([e["type"] for e in self.events()], ["ready_withdrawn", "ready_for_approval"])

    def test_nothing_is_withdrawn_unless_it_was_ready_and_a_colleagues(self):
        self.handle(pr(1, mine=False, requested=True), ("posted", "opus"), seen={**READY_SEEN, "verdict": "posted"})
        self.handle(pr(2, mine=True), ("posted", "opus"))
        self.handle(pr(3, mine=False, requested=True), ("posted", "opus"), seen={})
        self.assertEqual(self.events(), [])

    def test_a_gate_skip_withdraws_nothing(self):
        self.handle(pr(mine=False, requested=True), None, seen={**READY_SEEN, "files": {"a.py": "2"}})
        self.assertEqual(self.events(), [])


class Endpoint(Store):
    def setUp(self):
        super().setUp()
        self.sock = f"{self.dir}/api.sock"
        self.rt = rq.Runtime()
        self.server = api.bind(self.rt, self.sock)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        db.COMMITS.append(self.rt.changes.touch)
        self.addCleanup(db.COMMITS.remove, self.rt.changes.touch)

    def add(self, n, type="ready_for_approval", head=HEAD):
        return rq.announce(type, dict(pr(n, mine=False, head=head), author={"login": "colleague"}), "clean")

    def get(self, query=""):
        return call(f"/v1/events{query}", self.sock)

    def timed(self, query):
        started = time.monotonic()
        return self.get(query)[2], time.monotonic() - started

    def later(self, seconds, action):
        timer = threading.Timer(seconds, action)
        timer.start()
        self.addCleanup(timer.cancel)

    def test_the_page_has_the_fixture_shape(self):
        self.add(1)
        status, headers, page = self.get("?since=x.0")
        self.assertEqual((status, headers["content-type"]), (200, "application/json; charset=utf-8"))
        self.assertEqual(shape(page, fixture("events"), ("events",)), [])
        self.assertEqual(shape(page["events"][0], fixture("events")["events"][0]), [])

    def test_without_since_it_subscribes_from_now(self):
        self.add(1)
        epoch = db.meta_get("events_epoch")
        self.assertEqual(self.get()[2], {"cursor": f"{epoch}.1", "reset": False, "events": []})

    def test_a_cursor_behind_the_head_gets_the_events_after_it_at_once(self):
        epoch = db.meta_get("events_epoch")
        for n in (1, 2, 3):
            self.add(n)
        page, took = self.timed(f"?since={epoch}.1&wait=10")
        self.assertEqual(([e["number"] for e in page["events"]], page["reset"], page["cursor"]),
                         ([2, 3], False, f"{epoch}.3"))
        self.assertLess(took, 1)

    def test_the_current_cursor_holds_until_the_wait_runs_out(self):
        self.add(1)
        cursor = self.get()[2]["cursor"]
        page, took = self.timed(f"?since={cursor}&wait=1")
        self.assertEqual(page, {"cursor": cursor, "reset": False, "events": []})
        self.assertGreaterEqual(took, 0.9)

    def test_the_current_cursor_wakes_on_a_new_event(self):
        cursor = self.get()[2]["cursor"]
        self.later(0.2, lambda: self.add(7))
        page, took = self.timed(f"?since={cursor}&wait=10")
        self.assertEqual(([e["number"] for e in page["events"]], page["reset"]), ([7], False))
        self.assertLess(took, 1)

    def test_a_cursor_of_another_store_gets_every_event_with_reset(self):
        for n in (1, 2):
            self.add(n)
        page, took = self.timed("?since=zzzzzz.2&wait=10")
        self.assertEqual(([e["number"] for e in page["events"]], page["reset"]), ([1, 2], True))
        self.assertLess(took, 1)

    def test_a_cursor_of_another_store_on_an_empty_one_resets_at_once(self):
        page, took = self.timed("?since=zzzzzz.9&wait=10")
        self.assertEqual((page["events"], page["reset"]), ([], True))
        self.assertLess(took, 1)

    def test_a_trimmed_cursor_resets_and_the_last_rows_stay(self):
        epoch = db.meta_get("events_epoch")
        with patch.object(db, "EVENTS_KEEP", 3):
            for n in range(1, 8):
                self.add(n)
        page = self.get(f"?since={epoch}.1")[2]
        self.assertEqual(([e["number"] for e in page["events"]], page["reset"]), ([5, 6, 7], True))
        self.assertEqual(self.get(f"?since={epoch}.4")[2]["reset"], False)

    def test_the_same_head_twice_is_one_row_with_a_stable_id(self):
        self.add(1)
        self.add(1)
        self.add(1, head=OTHER)
        ids = [e["id"] for e in self.get("?since=x.0")[2]["events"]]
        self.assertEqual(ids, [f"ready_for_approval:{MONOREPO}#1@{h[:12]}" for h in (HEAD, OTHER)])

    def test_wait_is_capped(self):
        self.assertEqual(self.get("?wait=61")[::2],
                         (400, api.error("bad_request", "wait must be an integer from 0 to 60")))


if __name__ == "__main__":
    unittest.main()
