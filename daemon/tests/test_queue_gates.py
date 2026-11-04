import os
import tempfile
import unittest
from unittest.mock import patch

from prs import GITOPS, HEAD, MONOREPO, pr, rq
from pr_loop import db

OTHER = "b" * 40


class Priority(unittest.TestCase):
    def order(self, prs, first):
        return [(p["repo"], p["number"]) for p in sorted(prs, key=lambda p: rq.priority(p, first))]

    def test_bumped_first_in_bump_order_then_mine_then_the_rest(self):
        prs = [pr(1, mine=False), pr(2, mine=True), pr(3, mine=False), pr(4, mine=True)]
        self.assertEqual(self.order(prs, {MONOREPO: [3, 1]}),
                         [(MONOREPO, 3), (MONOREPO, 1), (MONOREPO, 2), (MONOREPO, 4)])

    def test_a_bump_is_per_repo(self):
        prs = [pr(7, MONOREPO, mine=False), pr(7, GITOPS, mine=False)]
        self.assertEqual(self.order(prs, {GITOPS: [7]}), [(GITOPS, 7), (MONOREPO, 7)])

    def test_a_repo_without_bumps_is_fine(self):
        self.assertEqual(rq.priority(pr(1, GITOPS), {}), (True, 0, False))


class Decide(unittest.TestCase):
    seen = {"files": {"a.py": "1"}}

    def test_only_reviews_past_every_gate(self):
        self.assertIsNone(rq.decide(pr(additions=9999), {"rounds": 99, "hold": True, **self.seen}, {"a.py": "1"}, True))

    def test_a_first_sighting_is_reviewed(self):
        self.assertIsNone(rq.decide(pr(), {}, {"a.py": "1"}, False))
        self.assertIsNone(rq.decide(pr(mine=False, requested=True), {}, {"a.py": "1"}, False))

    def test_baseline_for_a_pr_i_reviewed_or_a_colleague_approved(self):
        self.assertEqual(rq.decide(pr(mine=False), {}, {}, False),
                         ("baseline", "reviewed by me before — watching from this head on"))
        self.assertEqual(rq.decide(pr(approvals=(False,)), {}, {}, False),
                         ("baseline", "approved by a colleague — watching from this head on"))

    def test_my_own_approval_is_no_baseline(self):
        self.assertIsNone(rq.decide(pr(approvals=(True,)), {}, {}, False))

    def test_unchanged_own_diff(self):
        self.assertEqual(rq.decide(pr(), self.seen, {"a.py": "1"}, False),
                         ("unchanged", "own diff unchanged (merge of base or rebase)"))

    def test_trivial_only_when_every_changed_file_is_trivial(self):
        seen = {"files": {"a.py": "1", "README.md": "1", "yarn.lock": "1"}}
        files = {"a.py": "1", "README.md": "2", "yarn.lock": "2", "logo.svg": "1"}
        self.assertEqual(rq.decide(pr(), seen, files, False),
                         ("trivial", "only trivial files: README.md, logo.svg, yarn.lock"))
        self.assertIsNone(rq.decide(pr(), seen, {**files, "a.py": "2"}, False))

    def test_a_removed_file_counts_as_changed(self):
        self.assertEqual(rq.decide(pr(), {"files": {"a.py": "1", "b.md": "1"}}, {"a.py": "1"}, False)[0], "trivial")

    def test_hold_waits_for_a_request(self):
        seen = {"hold": True, **self.seen}
        files = {"a.py": "2"}
        self.assertEqual(rq.decide(pr(), seen, files, False),
                         ("held", "clean before, review only on request: --next 1 or --pr 1"))
        self.assertIsNone(rq.decide(pr(requested=True), seen, files, False))

    def test_needs_human_at_the_round_cap(self):
        files = {"a.py": "2"}
        self.assertEqual(rq.decide(pr(), {"rounds": rq.ROUNDS, **self.seen}, files, False)[0], "needs-human")
        self.assertIsNone(rq.decide(pr(), {"rounds": rq.ROUNDS - 1, **self.seen}, files, False))

    def test_too_big_past_the_added_line_cap(self):
        self.assertEqual(rq.decide(pr(additions=4001), {}, {}, False),
                         ("too-big", "4001 added lines, review it by hand"))
        self.assertIsNone(rq.decide(pr(additions=4000), {}, {}, False))

    def test_gates_run_in_order(self):
        seen = {"hold": True, "rounds": rq.ROUNDS, "files": {"a.py": "1"}}
        self.assertEqual(rq.decide(pr(additions=9999), seen, {"a.py": "1"}, False)[0], "unchanged")
        self.assertEqual(rq.decide(pr(additions=9999), seen, {"a.py": "2"}, False)[0], "held")
        self.assertEqual(rq.decide(pr(additions=9999, requested=True), seen, {"a.py": "2"}, False)[0], "needs-human")


class FeedbackKey(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(rq.feedback_key(pr(reviews=2, threads=[(False, 3), (False, 1), (True, 5)])), f"{HEAD}:2:2:4")
        self.assertEqual(rq.feedback_key(pr()), f"{HEAD}:0:0:0")

    def test_conflict(self):
        self.assertEqual(rq.feedback_key(pr(mergeable="CONFLICTING")), f"{HEAD}:0:0:0:conflict")
        self.assertEqual(rq.feedback_key(pr(mergeable="UNKNOWN")), f"{HEAD}:0:0:0")

    def test_red_ci_counts_failures_and_timeouts(self):
        key = rq.feedback_key(pr(counts={"FAILURE": 1, "TIMED_OUT": 2, "SUCCESS": 9}))
        self.assertEqual(key, f"{HEAD}:0:0:0:ci-red-3")

    def test_running_runs_move_the_key_only_on_a_red_head(self):
        self.assertEqual(rq.feedback_key(pr(counts={"FAILURE": 1, "IN_PROGRESS": 1})), f"{HEAD}:0:0:0:ci-red-1-running")
        for state in ("QUEUED", "PENDING", "WAITING", "IN_PROGRESS"):
            self.assertTrue(rq.feedback_key(pr(counts={"FAILURE": 1, state: 1})).endswith("-running"))
        self.assertEqual(rq.feedback_key(pr(counts={"IN_PROGRESS": 4})), f"{HEAD}:0:0:0")

    def test_order_of_the_suffixes(self):
        key = rq.feedback_key(pr(mergeable="CONFLICTING", counts={"FAILURE": 1}))
        self.assertEqual(key, f"{HEAD}:0:0:0:conflict:ci-red-1")

    def test_no_rollup(self):
        self.assertEqual(rq.feedback_key(pr(counts=None)), f"{HEAD}:0:0:0")

    def test_counts_colleagues_comments_after_the_head_commit(self):
        after, before = "2026-10-25T11:00:00+00:00", "2026-10-25T09:00:00+00:00"
        talk = [(after, False, "User"), (after, False, "User"), (before, False, "User"), (after, True, "User"),
                (after, False, "Bot")]
        key = rq.feedback_key(pr(talk=talk, mergeable="CONFLICTING"))
        self.assertEqual(key, f"{HEAD}:0:0:0:comments-2:conflict")
        self.assertEqual(rq.feedback_key(pr(talk=talk[2:])), f"{HEAD}:0:0:0")


class Lanes(unittest.TestCase):
    def reviewed(self, status="posted", sha=HEAD, **extra):
        return {"1": {"sha": sha, "status": status, **extra}}

    def test_fixable_needs_my_pr_a_settled_review_and_a_new_key(self):
        p = pr()
        self.assertTrue(rq.fixable(p, self.reviewed(), {}))
        self.assertTrue(rq.fixable(p, self.reviewed(), {"1": {"key": "old"}}))
        self.assertFalse(rq.fixable(p, self.reviewed(), {"1": {"key": rq.feedback_key(p)}}))

    def test_fixable_is_not_for_a_colleagues_pr_or_a_no_auto_fix_label(self):
        self.assertFalse(rq.fixable(pr(mine=False), self.reviewed(), {}))
        self.assertFalse(rq.fixable(pr(labels=[rq.NO_FIX]), self.reviewed(), {}))

    def test_fixable_waits_for_the_review_of_this_head(self):
        self.assertFalse(rq.fixable(pr(), {}, {}))
        self.assertFalse(rq.fixable(pr(), self.reviewed(sha=OTHER), {}))
        self.assertFalse(rq.fixable(pr(), self.reviewed("limited"), {}))

    def test_fixable_skips_the_review_gate_when_nothing_reviews_the_pr(self):
        self.assertTrue(rq.fixable(pr(labels=[rq.NO_REVIEW]), {}, {}))
        self.assertTrue(rq.fixable(pr(repo=GITOPS), {}, {}))

    def test_fixing_is_owed_after_a_posted_review_until_a_pass_ran_on_the_head(self):
        self.assertTrue(rq.fixing(pr(), self.reviewed(), {}))
        self.assertTrue(rq.fixing(pr(), self.reviewed(), {"1": {"sha": OTHER, "key": "k"}}))
        self.assertFalse(rq.fixing(pr(), self.reviewed(), {"1": {"sha": HEAD, "key": "k"}}))

    def test_fixing_again_after_an_errored_pass(self):
        self.assertTrue(rq.fixing(pr(), self.reviewed(), {"1": {"sha": HEAD, "key": None}}))

    def test_fixing_only_for_posted_reviews_on_my_unlabeled_pr(self):
        self.assertFalse(rq.fixing(pr(), self.reviewed("clean"), {}))
        self.assertFalse(rq.fixing(pr(), {}, {}))
        self.assertFalse(rq.fixing(pr(mine=False), self.reviewed(), {}))
        self.assertFalse(rq.fixing(pr(labels=[rq.NO_FIX]), self.reviewed(), {}))


class Ready(unittest.TestCase):
    def test_colleagues_pr_is_ready_on_a_clean_or_quality_only_verdict(self):
        p = pr(mine=False)
        self.assertTrue(rq.ready(p, {"verdict": "clean"}, {}))
        self.assertTrue(rq.ready(p, {"verdict": "quality-only"}, {}))
        self.assertFalse(rq.ready(p, {"verdict": "posted"}, {}))
        self.assertFalse(rq.ready(p, {}, {}))

    def test_my_pr_with_a_posted_review_is_ready_once_a_pass_on_the_head_settled(self):
        seen = {"status": "posted", "verdict": "posted"}
        for status in rq.SETTLED:
            self.assertTrue(rq.ready(pr(), seen, {"sha": HEAD, "status": status}))
        for status in ("pushed", "tests-red", "ci-stuck", "error", "limited"):
            self.assertFalse(rq.ready(pr(), seen, {"sha": HEAD, "status": status}))
        self.assertFalse(rq.ready(pr(), seen, {"sha": OTHER, "status": "nothing-to-fix"}))
        self.assertFalse(rq.ready(pr(), seen, {}))

    def test_my_clean_pr_is_ready_unless_a_pass_on_the_head_did_not_settle(self):
        seen = {"status": "clean", "verdict": "clean"}
        self.assertTrue(rq.ready(pr(), seen, {}))
        self.assertTrue(rq.ready(pr(), seen, {"sha": OTHER, "status": "tests-red"}))
        self.assertTrue(rq.ready(pr(), seen, {"sha": HEAD, "status": "no-changes"}))
        self.assertFalse(rq.ready(pr(), seen, {"sha": HEAD, "status": "tests-red"}))

    def test_vocabulary(self):
        self.assertEqual(rq.READY, ("clean", "quality-only"))
        self.assertEqual(rq.SETTLED, ("nothing-to-fix", "refuted-only", "no-changes"))


class Row(unittest.TestCase):
    def seen(self, status="clean", verdict="clean", sha=HEAD, **extra):
        return {"sha": sha, "status": status, "verdict": verdict, "at": "2026-10-25 10:00:00", **extra}

    def test_live_runs_come_first(self):
        self.assertEqual(rq.row(pr(), {}, {1: "review 10:01:02"}, []), (0, "reviewing", "since 10:01:02"))
        self.assertEqual(rq.row(pr(), {}, {1: "fix 10:01:02"}, []), (0, "fixing", "since 10:01:02"))

    def test_queued(self):
        group, status, detail = rq.row(pr(), {}, {}, [])
        self.assertEqual((group, status), (1, "queued"))
        self.assertTrue(detail.startswith("pushed "))
        self.assertEqual(rq.row(pr(), self.seen(sha=OTHER), {}, [])[:2], (1, "queued"))

    def test_ready(self):
        self.assertEqual(rq.row(pr(mine=False), self.seen(), {}, []), (3, "ready", "2026-10-25 10:00:00"))
        self.assertEqual(rq.row(pr(mine=False), self.seen("posted", "quality-only"), {}, []),
                         (3, "ready", "quality notes only"))
        self.assertEqual(rq.row(pr(), self.seen("posted", "posted"), {}, [], {"sha": HEAD, "status": "refuted-only"}),
                         (3, "ready", "fix refuted-only"))

    def test_a_posted_head_waits_on_the_fix_lane(self):
        seen = self.seen("posted", "posted")
        self.assertEqual(rq.row(pr(), seen, {}, []), (4, "posted", "fix queued"))
        self.assertEqual(rq.row(pr(labels=[rq.NO_FIX]), seen, {}, []), (4, "posted", rq.NO_FIX))
        self.assertEqual(rq.row(pr(), seen, {}, [], {"sha": HEAD, "status": "tests-red"}), (4, "posted", "fix tests-red"))
        self.assertEqual(rq.row(pr(mine=False), seen, {}, []), (4, "posted", "2026-10-25 10:00:00"))

    def test_idle_rows(self):
        self.assertEqual(rq.row(pr(labels=[rq.NO_REVIEW]), {}, {}, []), (4, "skipped", rq.NO_REVIEW))
        self.assertEqual(rq.row(pr(repo=GITOPS), {}, {}, []), (4, "skipped", rq.NO_REVIEW))
        self.assertEqual(rq.row(pr(mine=False), {}, {}, []), (4, "new", "baseline on next run"))
        self.assertEqual(rq.row(pr(), self.seen(sha=OTHER, hold=True), {}, []), (4, "held", "--next 1 to review"))

    def test_a_request_beats_a_baseline_and_a_hold(self):
        baseline = self.seen("baseline", None, sha=OTHER)
        self.assertEqual(rq.row(pr(mine=False, requested=True), baseline, {}, [])[:2], (1, "queued"))
        self.assertEqual(rq.row(pr(mine=False), baseline, {}, [1])[:2], (1, "queued"))
        self.assertEqual(rq.row(pr(requested=True), self.seen(sha=OTHER, hold=True), {}, [])[:2], (1, "queued"))


class FalseClean(unittest.TestCase):
    clean = "Read the whole diff and found nothing that needs a change in this PR."

    def test_short_or_empty_summary_is_false(self):
        for summary in ("", None, "ok", "x" * 39):
            self.assertTrue(rq.false_clean({"reason": "no-findings", "summary": summary}))

    def test_error_looking_summaries_are_false(self):
        for text in ("API Error: 529 overloaded_error from the upstream engine", "Hit a rate limit, so nothing ran",
                     "No review report was produced by the reviewer engine", "(none)"):
            self.assertTrue(rq.false_clean({"reason": "no-findings", "summary": text}), text)

    def test_a_real_summary_is_clean(self):
        self.assertFalse(rq.false_clean({"reason": "no-findings", "summary": self.clean}))
        self.assertFalse(rq.false_clean({"reason": "no-findings", "summary": "x" * 40}))

    def test_only_no_findings_can_be_false(self):
        self.assertFalse(rq.false_clean({"reason": "notes-only", "summary": ""}))
        self.assertFalse(rq.false_clean({"posted": True}))


class FixNote(unittest.TestCase):
    def test_pushed(self):
        res = {"status": "pushed", "pushed": "f" * 40, "fixed": 2, "refuted": 1, "deferred": 0}
        self.assertEqual(rq.fix_note(res, ""), "pushed ffffffffffff: 2 fixed, 1 refuted, 0 deferred")
        self.assertEqual(rq.fix_note({**res, "merged": True}, ""),
                         "pushed ffffffffffff: merged the base, 2 fixed, 1 refuted, 0 deferred")

    def test_tests_red(self):
        res = {"status": "tests-red", "failing": ["a.b", "c.d"], "worktree": "/wt"}
        self.assertEqual(rq.fix_note(res, "", rq.effective(MONOREPO)["fix"]["gates"]), "Karma red in a.b, c.d — /wt")

    def test_error_is_the_last_stderr_line_capped_at_200_chars(self):
        self.assertEqual(rq.fix_note({}, "first\nlast line\n"), "last line")
        self.assertEqual(rq.fix_note({"status": "error"}, "x" * 300), "x" * 200)
        self.assertEqual(rq.fix_note({}, "  \n"), "pr_fix.py printed nothing")

    def test_other_statuses_give_the_summary_or_the_status(self):
        self.assertEqual(rq.fix_note({"status": "refuted-only", "summary": " all refuted "}, ""), "all refuted")
        self.assertEqual(rq.fix_note({"status": "nothing-to-fix"}, ""), "nothing-to-fix")
        self.assertEqual(rq.fix_note({"status": "ci-stuck", "summary": "s" * 200}, ""), "s" * 160)


class Verdicts(unittest.TestCase):
    """handle() maps a review outcome to the verdict, rounds, hold and files it records."""

    SEEN = {"sha": OTHER, "status": "posted", "verdict": "posted", "rounds": 2, "hold": False,
            "files": {"old.py": "1"}}

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        patcher = patch.object(db, "DB", os.path.join(self.dir.name, "state.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db.close)
        self.addCleanup(self.dir.cleanup)

    def handle(self, p, outcome, seen=SEEN, files=None, first=()):
        files = {"a.py": "1"} if files is None else files
        recorded = []
        with patch.object(rq, "load", return_value={str(p["number"]): seen}), \
                patch.object(rq, "fingerprint", return_value=files), \
                patch.object(rq, "review", return_value=outcome), \
                patch.object(rq, "record", side_effect=lambda repo, key, entry, kind=rq.STATE: recorded.append(
                    (repo, key, entry))), \
                patch.object(rq, "post_clean_notice") as notice, \
                patch.object(rq, "in_review"), patch.object(rq, "kick") as kick, \
                patch.object(rq, "save_bumped"), patch.object(rq, "bumped", return_value=[]), \
                patch.object(rq, "log_once"), patch.object(rq, "log"):
            rq.handle(p, list(first), False, False)
        (repo, key, entry), = recorded
        self.assertEqual((repo, key), (p["repo"], str(p["number"])))
        return entry, notice, kick

    def events(self):
        return db.events_after("x.0")["events"]

    def test_clean_on_my_pr_holds_it_and_posts_the_notice(self):
        entry, notice, kick = self.handle(pr(), ("clean", "no findings"))
        self.assertEqual((entry["verdict"], entry["rounds"], entry["hold"], entry["files"]),
                         ("clean", 0, True, {"a.py": "1"}))
        notice.assert_called_once_with(MONOREPO, 1, HEAD)
        self.assertEqual(self.events(), [])
        kick.assert_not_called()

    def test_clean_on_a_colleagues_pr_emits_ready_and_does_not_hold(self):
        entry, _, _ = self.handle(pr(mine=False, requested=True), ("clean", "no findings"))
        self.assertEqual((entry["verdict"], entry["hold"]), ("clean", False))
        (e,) = self.events()
        self.assertEqual((e["type"], e["key"], e["title"]), ("ready_for_approval", f"{MONOREPO}#1", "title 1"))

    def test_posted_findings_add_a_round_and_kick_the_fix_lane_on_my_pr(self):
        entry, _, kick = self.handle(pr(), ("posted", "opus, codex"))
        self.assertEqual((entry["verdict"], entry["rounds"], entry["hold"]), ("posted", 3, False))
        kick.assert_called_once_with()
        self.assertEqual(self.events(), [])

    def test_posted_quality_notes_only_are_ready(self):
        entry, _, kick = self.handle(pr(mine=False, requested=True), ("posted", "quality"))
        self.assertEqual((entry["verdict"], entry["rounds"]), ("quality-only", 3))
        (e,) = self.events()
        self.assertEqual((e["type"], e["verdict"]), ("ready_for_approval", "quality-only"))
        kick.assert_not_called()
        entry, _, kick = self.handle(pr(), ("posted", "quality"))
        self.assertEqual(entry["verdict"], "quality-only")
        self.assertEqual(self.events(), [e])
        kick.assert_called_once()

    def test_posted_by_several_reviewers_is_not_quality_only(self):
        self.assertEqual(self.handle(pr(), ("posted", "quality, opus"))[0]["verdict"], "posted")

    def test_failed_has_no_verdict_and_keeps_the_old_files(self):
        entry, *_ = self.handle(pr(), ("failed", "opus failed 3×"))
        self.assertEqual((entry["verdict"], entry["rounds"], entry["files"]), (None, 2, {"old.py": "1"}))

    def test_limited_keeps_the_verdict_and_stays_off_the_bump_list(self):
        entry, *_ = self.handle(pr(), ("limited", "opus hit the usage limit of both engines"),
                                seen={**self.SEEN, "verdict": "clean", "hold": True}, first=[1])
        self.assertEqual((entry["verdict"], entry["rounds"], entry["hold"], entry["files"]),
                         ("clean", 2, True, {"old.py": "1"}))

    def test_a_bumped_pr_counts_as_requested(self):
        entry, *_ = self.handle(pr(mine=False), ("clean", "no findings"), first=[1])
        self.assertEqual(entry["verdict"], "clean")

    def test_gate_skips_keep_the_verdict_and_the_round_count(self):
        seen = {**self.SEEN, "verdict": "clean", "rounds": 0, "files": {"a.py": "1"}, "hold": True}
        entry, notice, *_ = self.handle(pr(), None, seen=seen)
        self.assertEqual((entry["status"], entry["verdict"], entry["rounds"], entry["hold"]), ("unchanged", "clean", 0, True))
        notice.assert_not_called()

    def test_baseline_has_no_verdict(self):
        entry, _, _ = self.handle(pr(mine=False), None, seen={}, files={"a.py": "1"})
        self.assertEqual((entry["status"], entry["verdict"], entry["rounds"], entry["files"]),
                         ("baseline", None, 0, {"a.py": "1"}))
        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main()
