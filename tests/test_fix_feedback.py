import contextlib
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from prs import check_run, pr_fix as fix

NODE = ". ~/.config/nvm/nvm.sh && nvm use 22.15.1 >/dev/null"
BUILD = "(cd .. && npm run postinstall) && npx shadow-cljs compile karma-test"


def karma_cmd(ns):
    return f"npx karma start --single-run --client.args iprally_ui.karma_runner_test.init --client.args {ns}"


def comment(login, body="text", key="author"):
    return {key: {"login": login}, "body": body}


class Namespaces(unittest.TestCase):
    def test_a_changed_test_is_its_own_namespace(self):
        self.assertEqual(fix.namespaces(["ui/test/iprally_ui/foo/bar_baz_test.cljs"]), ["iprally-ui.foo.bar-baz-test"])

    def test_a_changed_source_maps_to_the_test_beside_it(self):
        self.assertEqual(fix.namespaces(["ui/src/cljs/iprally_ui/foo/bar_baz.cljs"]), ["iprally-ui.foo.bar-baz-test"])

    def test_sorted_and_deduplicated(self):
        paths = ["ui/test/b_test.cljs", "ui/src/cljs/a.cljs", "ui/test/a_test.cljs", "ui/test/b_test.cljs"]
        self.assertEqual(fix.namespaces(paths), ["a-test", "b-test"])

    def test_other_paths_are_ignored(self):
        paths = ["ui/src/cljs/a.clj", "ui/src/cljc/a.cljs", "ui/test/a.cljs", "ui/test/a_test.clj", "src/a.cljs",
                 "ui/test/a_test.cljs.bak", "README.md"]
        self.assertEqual(fix.namespaces(paths), [])

    def test_an_unsafe_namespace_is_dropped(self):
        self.assertEqual(fix.namespaces(["ui/test/a b_test.cljs", "ui/test/a;b_test.cljs", "ui/test/ok_test.cljs"]),
                         ["ok-test"])


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


class Ui(unittest.TestCase):
    def popen(self, returncode=0, timeout=False):
        proc = MagicMock(pid=4242, returncode=returncode)
        proc.communicate.side_effect = [subprocess.TimeoutExpired("bash", 1), ("late",)] if timeout else [("out",)]
        return patch.object(fix.subprocess, "Popen", return_value=proc), proc

    def test_argv_and_options(self):
        patcher, _ = self.popen()
        with patcher as popen:
            self.assertEqual(fix.ui("/wt", "npx thing"), {"ok": True, "log": "out"})
        self.assertEqual(popen.call_args.args, (["bash", "-c", f"{NODE} && npx thing"],))
        self.assertEqual(popen.call_args.kwargs, {
            "cwd": "/wt/ui", "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
            "text": True, "start_new_session": True})

    def test_a_red_exit(self):
        patcher, _ = self.popen(returncode=1)
        with patcher:
            self.assertFalse(fix.ui("/wt", "x")["ok"])

    def test_a_timeout_kills_the_group_and_is_red(self):
        patcher, proc = self.popen(returncode=-9, timeout=True)
        with patcher, patch.object(fix.os, "killpg") as killpg:
            out = fix.ui("/wt", "npx thing")
        killpg.assert_called_once_with(4242, fix.signal.SIGKILL)
        self.assertEqual(out, {"ok": False, "log": f"late\nnpx thing timed out after {fix.UI_TIMEOUT} s"})


class Karma(unittest.TestCase):
    def test_one_build_then_one_run_per_namespace(self):
        with patch.object(fix, "ui", return_value={"ok": True, "log": "l"}) as ui:
            out = fix.karma("/wt", ["a-test", "b.c-test"])
        self.assertEqual([c.args for c in ui.call_args_list],
                         [("/wt", BUILD), ("/wt", karma_cmd("a-test")), ("/wt", karma_cmd("b.c-test"))])
        self.assertEqual(out, [{"ns": "a-test", "ok": True, "log": "l"}, {"ns": "b.c-test", "ok": True, "log": "l"}])

    def test_a_failed_build_is_the_only_result(self):
        with patch.object(fix, "ui", return_value={"ok": False, "log": "boom"}) as ui:
            out = fix.karma("/wt", ["a-test"])
        self.assertEqual(out, [{"ns": "shadow-cljs compile karma-test", "ok": False, "log": "boom"}])
        ui.assert_called_once_with("/wt", BUILD)

    def test_the_literal_commands(self):
        self.assertEqual(NODE, fix.NODE)
        self.assertEqual(karma_cmd("x"), "npx karma start --single-run --client.args "
                                         "iprally_ui.karma_runner_test.init --client.args x")


class Gate(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.wt = temp.name
        os.makedirs(f"{self.wt}/ui/test/iprally_ui")
        for name in ("foo_test", "bar_test"):
            open(f"{self.wt}/ui/test/iprally_ui/{name}.cljs", "w").close()

    def gate(self, paths, cljfmt="/bin/cljfmt", node_modules=True):
        if node_modules:
            os.makedirs(f"{self.wt}/ui/node_modules", exist_ok=True)
        with patch.object(fix, "changed", return_value=paths), patch.object(fix.shutil, "which", return_value=cljfmt), \
                patch.object(fix.subprocess, "run") as run, patch.object(fix, "karma_slot") as slot, \
                patch.object(fix, "karma", return_value=["karma result"]) as karma:
            slot.return_value = contextlib.nullcontext()
            out = fix.gate(self.wt)
        return out, run, karma, slot

    def test_cljfmt_fixes_the_changed_clojure_files(self):
        paths = ["a.clj", "b.cljs", "c.cljc", "d.edn", "e.py", "ui/test/iprally_ui/foo_test.cljs"]
        _, run, _, _ = self.gate(paths)
        run.assert_called_once_with(["cljfmt", "fix", "a.clj", "b.cljs", "c.cljc", "d.edn",
                                     "ui/test/iprally_ui/foo_test.cljs"], cwd=self.wt, capture_output=True)

    def test_no_cljfmt_run_without_clojure_files_or_the_binary(self):
        self.assertFalse(self.gate(["e.py"])[1].called)
        self.assertFalse(self.gate(["a.clj"], cljfmt=None)[1].called)

    def test_karma_runs_the_existing_test_namespaces_in_a_slot(self):
        paths = ["ui/test/iprally_ui/foo_test.cljs", "ui/src/cljs/iprally_ui/bar.cljs", "ui/src/cljs/iprally_ui/gone.cljs"]
        out, _, karma, slot = self.gate(paths)
        self.assertEqual(out, ["karma result"])
        karma.assert_called_once_with(self.wt, ["iprally-ui.bar-test", "iprally-ui.foo-test"])
        slot.assert_called_once_with()

    def test_nothing_to_test_means_no_slot_and_no_results(self):
        out, _, karma, slot = self.gate(["README.md", "ui/src/cljs/iprally_ui/gone.cljs"])
        self.assertEqual(out, [])
        self.assertFalse(karma.called or slot.called)

    def test_missing_node_modules_leaves_the_grade_to_ci(self):
        out, _, karma, slot = self.gate(["ui/test/iprally_ui/foo_test.cljs"], node_modules=False)
        self.assertEqual(out, [{"ns": "iprally-ui.foo-test", "ok": None, "log": "ui/node_modules missing, CI grades it"}])
        self.assertFalse(karma.called or slot.called)

    def test_the_whole_argv_chain(self):
        with patch.object(fix, "ui", return_value={"ok": True, "log": ""}) as ui:
            with patch.object(fix, "changed", return_value=["ui/src/cljs/iprally_ui/foo.cljs"]), \
                    patch.object(fix, "karma_slot", return_value=contextlib.nullcontext()):
                os.makedirs(f"{self.wt}/ui/node_modules")
                fix.gate(self.wt)
        self.assertEqual([c.args for c in ui.call_args_list],
                         [(self.wt, BUILD), (self.wt, karma_cmd("iprally-ui.foo-test"))])


if __name__ == "__main__":
    unittest.main()
