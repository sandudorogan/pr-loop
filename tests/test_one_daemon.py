import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("review_queue", str(ROOT / "bin/review-queue"))
spec = importlib.util.spec_from_loader("review_queue", loader)
rq = importlib.util.module_from_spec(spec)
loader.exec_module(rq)

GITOPS = "iprally/gitops"


def node(repo, number, mine=True, title="t"):
    return {"number": number, "title": f"{title} {number}", "state": "OPEN", "isDraft": False,
            "headRefOid": f"{number:040d}", "baseRefName": "main", "additions": 1, "deletions": 0,
            "viewerDidAuthor": mine, "mergeable": "MERGEABLE", "repository": {"nameWithOwner": repo},
            "labels": {"nodes": []}, "latestOpinionatedReviews": {"nodes": []},
            "commits": {"nodes": [{"commit": {"committedDate": "2026-10-25T10:00:00Z", "statusCheckRollup": None}}]},
            "reviews": {"totalCount": 0}, "reviewThreads": {"nodes": []}}


def search(mine=(), requested=(), reviewed=()):
    return json.dumps({"data": {"mine": {"nodes": list(mine)}, "requested": {"nodes": list(requested)},
                                "reviewed": {"nodes": list(reviewed)}}})


class OneDaemon(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = temp.name
        patcher = patch.object(rq, "STATE_DIR", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, out):
        with patch.object(rq, "sh", return_value=out) as sh:
            prs = rq.queue()
        return prs, sh.call_args.args

    def test_query_has_the_repo_and_one_qualifier_per_repo(self):
        self.assertIn("repository { nameWithOwner }", rq.QUEUE_QUERY)
        self.assertEqual(rq.QUEUE_QUERY.count("search("), 3)
        _, args = self.fetch(search())
        scope = "repo:iprally/iprally repo:iprally/gitops is:pr is:open"
        self.assertIn(f"mine={scope} author:@me", args)
        self.assertIn(f"requested={scope} user-review-requested:@me", args)
        self.assertIn(f"reviewed={scope} reviewed-by:@me -author:@me", args)

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
        names = {kind: (Path(rq.path(rq.MONOREPO, kind)).name, Path(rq.path(GITOPS, kind)).name)
                 for kind in (rq.STATE, rq.FIXES, rq.NEXT, rq.LOCKS, rq.NOWS, rq.LOCK, rq.PID)}
        self.assertEqual(names, {
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
        Path(rq.path(GITOPS, rq.NEXT)).write_text("[3]")
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
