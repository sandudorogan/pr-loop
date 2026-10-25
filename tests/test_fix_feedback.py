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


if __name__ == "__main__":
    unittest.main()
