from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from prs import check_run, pr_fix as fix


def comment(login, body="text", key="author"):
    return {key: {"login": login}, "body": body}


class MineLast(unittest.TestCase):
    def test_my_plain_reply_ends_the_thread(self):
        self.assertTrue(fix.mine_last([comment("rev"), comment("me", "refuted: it is fine")], "me"))

    def test_my_agent_comment_does_not(self):
        marked = f"{fix.AGENT_MARKER} reviewer=opus round=1 sha=abc -->\n**[high] t**"
        self.assertFalse(fix.mine_last([comment("me", marked)], "me"))

    def test_someone_elses_last_word_does_not(self):
        self.assertFalse(fix.mine_last([comment("me"), comment("rev")], "me"))

    def test_the_login_may_sit_under_user_and_a_deleted_author_is_a_ghost(self):
        self.assertTrue(fix.mine_last([comment("me", key="user")], "me"))
        self.assertFalse(fix.mine_last([{"author": None, "body": "x"}], "me"))
        self.assertEqual(fix.login({"author": None}), "ghost")

    def test_an_empty_body_counts_as_unmarked(self):
        self.assertTrue(fix.mine_last([{"author": {"login": "me"}, "body": None}], "me"))


class Rerun(unittest.TestCase):
    def rerun(self, jobs, runs):
        calls = []

        def gh(*args):
            calls.append(args)
            return runs.get(int(args[-1].split("/")[-1])) if len(args) == 1 else None

        with patch.object(fix, "gh", gh):
            return fix.rerun(jobs), [a[-1].split("actions/")[1] for a in calls if a[0] == "-X"]

    def test_two_jobs_of_one_finished_run_take_one_rerun(self):
        jobs = [{"id": 1, "run": 7, "head": "a"}, {"id": 2, "run": 7, "head": "a"}]
        waiting, posts = self.rerun(jobs, {7: {"status": "completed", "conclusion": "failure"}})
        self.assertEqual((waiting, posts), ([], ["runs/7/rerun-failed-jobs"]))

    def test_a_running_run_waits_and_a_green_one_is_dropped(self):
        jobs = [{"id": 1, "run": 7, "head": "a"}, {"id": 2, "run": 8, "head": "a"}]
        runs = {7: {"status": "in_progress", "conclusion": None}, 8: {"status": "completed", "conclusion": "success"}}
        self.assertEqual(self.rerun(jobs, runs), (jobs[:1], []))


class Stuck(unittest.TestCase):
    state = {"ci_tries": {"build": ["a", "b", "c"], "lint": ["a", "b"], "e2e": ["a", "b", "c", "d"]}}

    def test_failed_jobs_with_the_try_cap_reached(self):
        jobs = [check_run("build"), check_run("lint"), check_run("e2e", "timed_out"), check_run("new")]
        self.assertEqual(fix.stuck(jobs, self.state), ["build", "e2e"])

    def test_green_cancelled_and_untried_jobs_never_stick(self):
        jobs = [check_run("build", "success"), check_run("e2e", "cancelled"), check_run("lint", None)]
        self.assertEqual(fix.stuck(jobs, self.state), [])
        self.assertEqual(fix.stuck([check_run("build")], {}), [])

    def test_the_cap(self):
        self.assertEqual(fix.CI_TRIES, 3)


class FailedJobs(unittest.TestCase):
    def jobs(self, jobs, state, log="log"):
        with patch.object(fix, "sh", return_value=log) as sh:
            return fix.failed_jobs(jobs, state), sh

    def test_item_shape_and_log_request(self):
        items, sh = self.jobs([check_run("build", job=5, run=77)], {"ci_tries": {"build": ["earlier"]}}, "tail")
        self.assertEqual(items, [{"ref": "ci:5", "kind": "ci", "name": "build", "id": 5, "run": 77,
                                  "url": "https://github.com/o/r/actions/runs/77/job/5",
                                  "refuted_before": ["earlier"], "log": "tail"}])
        sh.assert_called_once_with(["gh", "api", "--allow-escape-sequences", f"repos/{fix.REPO}/actions/jobs/5/logs"])

    def test_skips_green_handled_and_stuck_jobs(self):
        jobs = [check_run("a", "success", 1), check_run("b", "failure", 2), check_run("c", "failure", 3),
                check_run("d", "timed_out", 4), check_run("e", "failure", 5)]
        state = {"handled_jobs": [2], "ci_tries": {"e": ["x", "y", "z"]}}
        items, _ = self.jobs(jobs, state)
        self.assertEqual([i["name"] for i in items], ["c", "d"])

    def test_log_noise_is_stripped_and_the_tail_kept(self):
        raw = "2026-10-25T10:00:00.1234567Z \x1b[31mred\x1b[0m line\n2026-10-25T10:00:01Z next"
        items, _ = self.jobs([check_run()], {}, raw)
        self.assertEqual(items[0]["log"], "red line\nnext")
        items, _ = self.jobs([check_run()], {}, "x" * (fix.CI_LOG_CHARS + 5))
        self.assertEqual(len(items[0]["log"]), fix.CI_LOG_CHARS)


class Conversation(unittest.TestCase):
    def test_colleagues_comments_after_the_head_commit_not_yet_handled(self):
        def issue(id, login, kind="User", at="2026-11-02T11:48:07Z"):
            return {"id": id, "user": {"login": login, "type": kind}, "body": f"body {id}", "created_at": at,
                    "html_url": f"https://github.com/o/r/pull/7#issuecomment-{id}"}
        pages = [[issue(1, "rev"), issue(2, "me"), issue(3, "pvbctl", "Bot"), issue(4, "rev", at="2026-10-23T11:00:00Z")],
                 [issue(5, "rev"), issue(6, "other")]]
        commit = {"commit": {"committer": {"date": "2026-10-23T11:24:46Z"}}}
        with patch.object(fix, "gh", side_effect=[commit, pages]) as gh:
            items = fix.conversation(7, "abc", "me", [5])
        self.assertEqual([i["id"] for i in items], [1, 6])
        self.assertEqual(items[0], {"ref": "comment:1", "kind": "comment", "author": "rev", "body": "body 1",
                                    "url": "https://github.com/o/r/pull/7#issuecomment-1", "id": 1})
        gh.assert_any_call(f"repos/{fix.REPO}/commits/abc")


class Resumes(unittest.TestCase):
    red = {"head": "h", "base": "b"}

    def meta(self, head="h", base="b", mergeable="MERGEABLE"):
        return {"headRefOid": head, "baseRefOid": base, "mergeable": mergeable}

    def test_a_red_tree_resumes_on_the_same_head(self):
        self.assertTrue(fix.resumes(self.red, self.meta(base="moved")))
        self.assertTrue(fix.resumes(self.red, self.meta(mergeable="CONFLICTING")))

    def test_a_new_head_or_a_moved_base_under_a_conflict_starts_over(self):
        self.assertFalse(fix.resumes(self.red, self.meta(head="new")))
        self.assertFalse(fix.resumes(self.red, self.meta(base="moved", mergeable="CONFLICTING")))
        self.assertFalse(fix.resumes({"head": "h"}, self.meta(mergeable="CONFLICTING")))
        self.assertFalse(fix.resumes({}, self.meta()))


class Worktree(unittest.TestCase):
    """worktree() against a real origin: a clone at `root`, the PR branch `f` on top of `main`."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        origin, self.root = (os.path.join(self.dir.name, d) for d in ("origin", "root"))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
        subprocess.run(["git", "clone", "-q", origin, self.root], check=True, capture_output=True)
        self.commit("base", "main")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "-b", "f")
        self.head = self.commit("feature", "f")
        self.git("push", "-q", "origin", "f")
        self.git("checkout", "-q", "main")
        self.git("branch", "-q", "-D", "f")
        real = fix.sh
        self.patches = [patch.object(fix, "REPO_ROOT", self.root),
                        patch.object(fix, "sh", lambda args, cwd=None, **kw: real(args, cwd or self.root, **kw))]
        for p in self.patches:
            p.start()
        self.wt = self.worktree({}, False)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.dir.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", cwd or self.root, *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, name, text, cwd=None):
        Path(cwd or self.root, name).write_text(text)
        self.git("add", name, cwd=cwd)
        self.git("commit", "-qm", name, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def worktree(self, red, resume, head=None):
        return fix.worktree({"headRefName": "f", "headRefOid": head or self.head}, red, resume)

    def test_a_rewritten_branch_whose_commits_the_head_holds_gives_way(self):
        self.git("checkout", "-q", "main")
        self.commit("other", "main moved")
        self.git("checkout", "-q", "-b", "g")
        rebased = self.commit("feature", "f")
        self.git("push", "-q", "-f", "origin", "g:f")
        self.worktree({}, False, rebased)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt), rebased)

    def test_a_commit_only_the_worktree_holds_stops_the_pass(self):
        self.commit("local", "not pushed", cwd=self.wt)
        self.git("checkout", "-q", "-b", "g", self.head)
        rewritten = self.commit("feature", "rewritten")
        self.git("push", "-q", "-f", "origin", "g:f")
        with self.assertRaises(SystemExit):
            self.worktree({}, False, rewritten)

    def test_red_work_stays_only_while_the_pass_resumes(self):
        Path(self.wt, "feature").write_text("red work")
        red = {"head": self.head, "paths": ["feature"]}
        self.worktree(red, True)
        self.assertEqual(Path(self.wt, "feature").read_text(), "red work")
        self.worktree(red, False)
        self.assertEqual(Path(self.wt, "feature").read_text(), "f")


if __name__ == "__main__":
    unittest.main()
