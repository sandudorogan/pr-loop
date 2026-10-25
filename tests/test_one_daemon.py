import contextlib
import fcntl
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prs  # noqa: F401
from pr_wizard import db, names, queue as rq

GITOPS = "iprally/gitops"


def node(repo, number, mine=True, title="t"):
    return {"number": number, "title": f"{title} {number}", "state": "OPEN", "isDraft": False,
            "headRefOid": f"{number:040d}", "baseRefName": "main", "additions": 1, "deletions": 0,
            "viewerDidAuthor": mine, "mergeable": "MERGEABLE", "repository": {"nameWithOwner": repo},
            "author": {"login": "me"}, "updatedAt": "2026-10-25T10:00:00Z",
            "labels": {"nodes": []}, "latestOpinionatedReviews": {"nodes": []},
            "commits": {"nodes": [{"commit": {"committedDate": "2026-10-25T10:00:00Z", "statusCheckRollup": None}}]},
            "reviews": {"totalCount": 0}, "reviewThreads": {"nodes": []}}


def search(mine=(), requested=(), assigned=(), reviewed=()):
    found = {"mine": mine, "requested": requested, "assigned": assigned, "reviewed": reviewed}
    return json.dumps({"data": {"rateLimit": {"cost": 1, "remaining": 4999},
                                **{alias: {"issueCount": len(nodes), "pageInfo": {"hasNextPage": False, "endCursor": None},
                                           "nodes": list(nodes)} for alias, nodes in found.items()}}})


class OneDaemon(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = temp.name
        for patcher in (patch.object(names, "STATE_DIR", self.state), patch.object(db, "DB", f"{self.state}/state.db")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(db.close)

    def fetch(self, out):
        with patch.object(rq, "sh", return_value=out) as sh:
            prs = rq.queue()
        return prs, sh.call_args.args

    def test_query_has_the_repo_and_no_repo_qualifier(self):
        self.assertIn("repository { nameWithOwner }", rq.FRAGMENT)
        _, args = self.fetch(search())
        self.assertIn("mine=is:pr is:open author:@me", args)
        self.assertIn("requested=is:pr is:open user-review-requested:@me", args)
        self.assertIn("assigned=is:pr is:open assignee:@me", args)
        self.assertIn("reviewed=is:pr is:open reviewed-by:@me -author:@me", args)
        self.assertFalse([a for a in args if "repo:" in a])

    def test_prs_carry_their_repo_and_the_same_number_does_not_collide(self):
        prs, _ = self.fetch(search(mine=[node(rq.MONOREPO, 7), node(GITOPS, 7)],
                                   requested=[node(GITOPS, 7)]))
        self.assertEqual([(p["repo"], p["number"], p["requested"]) for p in prs],
                         [(GITOPS, 7, True), (rq.MONOREPO, 7, False)])
        pending = rq.Pending(prs)
        with patch.object(rq, "bumps", return_value={rq.MONOREPO: [], GITOPS: []}):
            taken = {rq.pr_key(pending.take(False)[0]) for _ in range(2)}
        self.assertEqual(taken, {(rq.MONOREPO, 7), (GITOPS, 7)})
        pending.refill(prs)
        self.assertEqual(pending.prs, [])

    def test_path_helpers_keep_todays_names(self):
        found = {kind: (Path(names.path(rq.MONOREPO, kind)).name, Path(names.path(GITOPS, kind)).name)
                 for kind in (names.STATE, names.FIXES, names.NEXT, names.LOCKS, names.NOWS, names.LOCK, names.PID)}
        self.assertEqual(found, {
            ".json": ("review-queue.json", "review-queue-gitops.json"),
            ".fixes.json": ("review-queue.fixes.json", "review-queue-gitops.fixes.json"),
            ".next": ("review-queue.next", "review-queue-gitops.next"),
            ".locks": ("review-queue.locks", "review-queue-gitops.locks"),
            ".now.d": ("review-queue.now.d", "review-queue-gitops.now.d"),
            ".lock": ("review-queue.lock", "review-queue-gitops.lock"),
            ".pid": ("review-queue.pid", "review-queue-gitops.pid")})
        self.assertEqual(rq.LABEL, "local.review-queue")

    def test_children_run_in_their_repo(self):
        for repo, root in ((rq.MONOREPO, "iprally"), (GITOPS, "gitops")):
            run = rq.child(repo)
            self.assertEqual(run["cwd"], str(Path.home() / "workdir" / root))
            self.assertEqual((run["env"]["IPR_REPO"], run["env"]["IPR_REPO_ROOT"]), (repo, run["cwd"]))

    def test_review_lane_is_off_for_gitops(self):
        self.assertFalse(rq.unreviewed(dict(node(rq.MONOREPO, 1), repo=rq.MONOREPO)))
        self.assertTrue(rq.unreviewed(dict(node(GITOPS, 1), repo=GITOPS)))

    def test_a_held_legacy_lock_skips_its_repo(self):
        held = {}
        with open(rq.path(GITOPS, rq.LOCK), "w") as old:
            fcntl.flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(rq.serving(held), {rq.MONOREPO})
            self.assertIn("gitops#-", out.getvalue())
        self.assertEqual(rq.serving(held), {rq.MONOREPO, GITOPS})
        self.addCleanup(held[GITOPS].close)

    def test_list_mixes_both_repos_in_priority_order(self):
        db.bump(GITOPS, 3)
        prs = [dict(node(rq.MONOREPO, 5, mine=False), repo=rq.MONOREPO, requested=True),
               dict(node(GITOPS, 3), repo=GITOPS, requested=False),
               dict(node(rq.MONOREPO, 3), repo=rq.MONOREPO, requested=False)]
        with patch.object(rq, "unreviewed", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            rq.show(prs)
        self.assertEqual([line.split()[:2] for line in out.getvalue().splitlines()],
                         [["1", "gitops#3"], ["2", "#3"], ["3", "#5"]])


if __name__ == "__main__":
    unittest.main()
