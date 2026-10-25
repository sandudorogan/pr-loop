import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from prs import pr_fix as fix
from pr_wizard import config, gates

NODE = ". ~/.config/nvm/nvm.sh && nvm use 22.15.1 >/dev/null"
BUILD = "(cd .. && npm run postinstall) && npx shadow-cljs compile karma-test"
IPRALLY = config.effective(config.DEFAULTS, "iprally/iprally")["fix"]["gates"]
CLJFMT, KARMA = IPRALLY
STEP_6 = ("6. Add or update a test when a fix changes behaviour. Do not run tests that need a JVM or a\n"
          "   browser (lein, Karma): they abort in this sandbox. The caller runs the Karma namespaces you\n"
          "   touch after you finish and sends any failure back to you.\n")
PRETTIER = {"name": "prettier", "kind": "format", "when": ["*.ts"], "cwd": "web", "run": "npx prettier --write {files}"}
PYTEST = {"name": "pytest", "kind": "test", "when": ["src/*.py", "tests/test_*.py"], "timeout_s": 60,
          "targets": {"map": [["^src/(.+)\\.py$", "tests/test_\\1.py"]], "keep": "^tests/(test_.+)\\.py$", "exists": True},
          "run": "python3 -m pytest tests/{item}.py", "protect": ["pytest.ini"]}


def karma_cmd(ns):
    return f"npx karma start --single-run --client.args iprally_ui.karma_runner_test.init --client.args {ns}"


def karma_ns(paths):
    return gates.items(KARMA | {"targets": KARMA["targets"] | {"exists": False}}, "/wt", paths)


def worktree(case, *files):
    temp = tempfile.TemporaryDirectory()
    case.addCleanup(temp.cleanup)
    for name in files:
        os.makedirs(os.path.dirname(f"{temp.name}/{name}") or temp.name, exist_ok=True)
        open(f"{temp.name}/{name}", "w").close()
    return temp.name


class Namespaces(unittest.TestCase):
    def test_a_changed_test_is_its_own_namespace(self):
        self.assertEqual(karma_ns(["ui/test/iprally_ui/foo/bar_baz_test.cljs"]), ["iprally-ui.foo.bar-baz-test"])

    def test_a_changed_source_maps_to_the_test_beside_it(self):
        self.assertEqual(karma_ns(["ui/src/cljs/iprally_ui/foo/bar_baz.cljs"]), ["iprally-ui.foo.bar-baz-test"])

    def test_sorted_and_deduplicated(self):
        paths = ["ui/test/b_test.cljs", "ui/src/cljs/a.cljs", "ui/test/a_test.cljs", "ui/test/b_test.cljs"]
        self.assertEqual(karma_ns(paths), ["a-test", "b-test"])

    def test_other_paths_are_ignored(self):
        paths = ["ui/src/cljs/a.clj", "ui/src/cljc/a.cljs", "ui/test/a.cljs", "ui/test/a_test.clj", "src/a.cljs",
                 "ui/test/a_test.cljs.bak", "README.md"]
        self.assertEqual(karma_ns(paths), [])
        self.assertEqual(gates.matching(KARMA, paths), [])

    def test_an_unsafe_namespace_is_dropped(self):
        self.assertEqual(karma_ns(["ui/test/a b_test.cljs", "ui/test/a;b_test.cljs", "ui/test/ok_test.cljs"]),
                         ["ok-test"])


class Execute(unittest.TestCase):
    def popen(self, returncode=0, timeout=False):
        proc = MagicMock(pid=4242, returncode=returncode)
        proc.communicate.side_effect = [subprocess.TimeoutExpired("bash", 1), ("late",)] if timeout else [("out",)]
        return patch.object(gates.subprocess, "Popen", return_value=proc), proc

    def test_argv_and_options(self):
        patcher, proc = self.popen()
        with patcher as popen:
            self.assertEqual(gates.execute(KARMA, "/wt", "npx thing"), {"ok": True, "log": "out"})
        self.assertEqual(popen.call_args.args, (["bash", "-c", f"{NODE} && npx thing"],))
        self.assertEqual(popen.call_args.kwargs, {
            "cwd": "/wt/ui", "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
            "text": True, "start_new_session": True})
        proc.communicate.assert_called_once_with(timeout=1800)

    def test_a_red_exit(self):
        patcher, _ = self.popen(returncode=1)
        with patcher:
            self.assertFalse(gates.execute(KARMA, "/wt", "x")["ok"])

    def test_a_timeout_kills_the_group_and_is_red(self):
        patcher, proc = self.popen(returncode=-9, timeout=True)
        with patcher, patch.object(gates.os, "killpg") as killpg:
            out = gates.execute(KARMA, "/wt", "npx thing")
        killpg.assert_called_once_with(4242, gates.signal.SIGKILL)
        self.assertEqual(out, {"ok": False, "log": "late\nnpx thing timed out after 1800 s"})

    def test_a_plain_command_without_a_prelude_runs_as_is(self):
        patcher, proc = self.popen()
        with patcher as popen:
            gates.execute(PYTEST, "/wt", "python3 -m pytest 'tests/a b.py'")
        self.assertEqual(popen.call_args.args, (["python3", "-m", "pytest", "tests/a b.py"],))
        self.assertEqual(popen.call_args.kwargs["cwd"], "/wt")
        proc.communicate.assert_called_once_with(timeout=60)


class Karma(unittest.TestCase):
    def setUp(self):
        self.wt = worktree(self, "ui/test/a_test.cljs", "ui/test/b/c_test.cljs", "ui/node_modules/x")
        self.files = ["ui/test/a_test.cljs", "ui/test/b/c_test.cljs"]

    def karma(self, result):
        with patch.object(gates, "execute", return_value=result) as execute, \
                patch.object(gates, "slot", return_value=contextlib.nullcontext()):
            return gates.test(KARMA, self.wt, self.files), execute

    def test_one_build_then_one_run_per_namespace(self):
        out, execute = self.karma({"ok": True, "log": "l"})
        self.assertEqual([c.args for c in execute.call_args_list],
                         [(KARMA, self.wt, BUILD), (KARMA, self.wt, karma_cmd("a-test")),
                          (KARMA, self.wt, karma_cmd("b.c-test"))])
        self.assertEqual(out, [{"gate": "Karma", "ns": "a-test", "ok": True, "log": "l"},
                               {"gate": "Karma", "ns": "b.c-test", "ok": True, "log": "l"}])

    def test_a_failed_build_is_the_only_result(self):
        out, execute = self.karma({"ok": False, "log": "boom"})
        self.assertEqual(out, [{"gate": "Karma", "ns": "shadow-cljs compile karma-test", "ok": False, "log": "boom"}])
        execute.assert_called_once_with(KARMA, self.wt, BUILD)

    def test_the_literal_commands(self):
        self.assertEqual(KARMA["prelude"], NODE)
        self.assertEqual(gates.render(KARMA["run"], [], "x"), karma_cmd("x"))
        self.assertEqual(KARMA["setup"]["run"], BUILD)
        self.assertEqual((KARMA["timeout_s"], KARMA["slot"], gates.SLOTS), (1800, True, 2))


class Gate(unittest.TestCase):
    def setUp(self):
        self.wt = worktree(self, "ui/test/iprally_ui/foo_test.cljs", "ui/test/iprally_ui/bar_test.cljs")

    def gate(self, paths, cljfmt="/bin/cljfmt", node_modules=True, gate_list=IPRALLY):
        if node_modules:
            os.makedirs(f"{self.wt}/ui/node_modules", exist_ok=True)
        with patch.object(gates.shutil, "which", return_value=cljfmt), patch.object(gates.subprocess, "run") as run, \
                patch.object(gates, "slot", return_value=contextlib.nullcontext()) as slot, \
                patch.object(gates, "execute", return_value={"ok": True, "log": ""}) as execute:
            out = gates.run(gate_list, self.wt, paths)
        return out, run, execute, slot

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
        out, _, execute, slot = self.gate(paths)
        self.assertEqual([c.args[2] for c in execute.call_args_list],
                         [BUILD, karma_cmd("iprally-ui.bar-test"), karma_cmd("iprally-ui.foo-test")])
        self.assertEqual([t["ns"] for t in out], ["iprally-ui.bar-test", "iprally-ui.foo-test"])
        slot.assert_called_once_with()

    def test_nothing_to_test_means_no_slot_and_no_results(self):
        out, _, execute, slot = self.gate(["README.md", "ui/src/cljs/iprally_ui/gone.cljs"])
        self.assertEqual(out, [])
        self.assertFalse(execute.called or slot.called)

    def test_missing_node_modules_leaves_the_grade_to_ci(self):
        out, _, execute, slot = self.gate(["ui/test/iprally_ui/foo_test.cljs"], node_modules=False)
        self.assertEqual(out, [{"gate": "Karma", "ns": "iprally-ui.foo-test", "ok": None,
                                "log": "ui/node_modules missing, CI grades it"}])
        self.assertFalse(execute.called or slot.called)

    def test_a_project_without_gates_runs_none(self):
        self.assertEqual(config.effective(config.DEFAULTS, "iprally/gitops")["fix"]["gates"], [])
        self.assertEqual(config.effective(config.DEFAULTS, "someone/else")["fix"]["gates"], [])
        out, run, execute, slot = self.gate(["a.clj", "ui/test/iprally_ui/foo_test.cljs"], gate_list=[])
        self.assertEqual(out, [])
        self.assertFalse(run.called or execute.called or slot.called)

    def test_a_custom_format_gate_gets_its_files_quoted(self):
        _, run, _, _ = self.gate(["web/a.ts", "b c.ts", "x.py"], gate_list=[PRETTIER])
        run.assert_called_once_with(["npx", "prettier", "--write", "web/a.ts", "b c.ts"], cwd=f"{self.wt}/web",
                                    capture_output=True)
        shell = PRETTIER | {"run": "npx prettier --write {files} && npx eslint --fix {files}"}
        _, run, _, _ = self.gate(["a.ts"], gate_list=[shell])
        self.assertEqual(run.call_args.args, (["bash", "-c", "npx prettier --write a.ts && npx eslint --fix a.ts"],))

    def test_a_test_gate_runs_once_per_existing_target(self):
        os.makedirs(f"{self.wt}/tests")
        for name in ("test_a.py", "test_b.py"):
            open(f"{self.wt}/tests/{name}", "w").close()
        out, _, execute, slot = self.gate(["src/a.py", "tests/test_b.py", "src/gone.py", "README.md"],
                                          gate_list=[PYTEST])
        self.assertEqual([c.args for c in execute.call_args_list],
                         [(PYTEST, self.wt, "python3 -m pytest tests/test_a.py"),
                          (PYTEST, self.wt, "python3 -m pytest tests/test_b.py")])
        self.assertEqual([(t["gate"], t["ns"]) for t in out], [("pytest", "test_a"), ("pytest", "test_b")])
        self.assertFalse(slot.called)

    def test_a_test_gate_without_targets_runs_once_with_its_files(self):
        lint = {"name": "mypy", "kind": "test", "when": ["*.py"], "run": "mypy {files}"}
        out, _, execute, _ = self.gate(["a.py", "b.py"], gate_list=[lint])
        execute.assert_called_once_with(lint, self.wt, "mypy a.py b.py")
        self.assertEqual(out, [{"gate": "mypy", "ns": "mypy", "ok": True, "log": ""}])


class Prompts(unittest.TestCase):
    def test_iprally_renders_step_6_as_before(self):
        self.assertIn(STEP_6, gates.fill(Path(fix.PROMPT).read_text(), IPRALLY))

    def test_no_gates_hands_the_checks_to_codex(self):
        text = gates.fill(Path(fix.PROMPT).read_text(), [])
        self.assertIn("6. Add or update a test when a fix changes behaviour. The caller runs no checks after you. Run\n"
                      "   the formatter, linter and tests that the conventions name, when they work offline in this\n"
                      "   sandbox.\n", text)
        self.assertNotIn("{GATES}", text)

    def test_the_karma_retry_prompt(self):
        self.assertEqual(gates.retry(IPRALLY, [{"gate": "Karma"}], "LOGS"),
                         "These Karma runs fail after your change:\n\nLOGS\n\n"
                         "Read each full log first: the cause is often above the tail. Fix what your "
                         "change broke. Never edit build or runner config (shadow-cljs.edn, "
                         "karma.conf.js, package.json) to make a run pass. When the build or the "
                         "runner fails and your change does not cause it, change nothing and say so "
                         "in `summary`. Return the same JSON as before, for the same refs.")

    def test_a_retry_names_only_the_red_gates_and_their_protected_files(self):
        out = gates.retry([*IPRALLY, PYTEST], [{"gate": "pytest"}], "LOGS")
        self.assertTrue(out.startswith("These pytest runs fail after your change:"))
        self.assertIn("Never edit build or runner config (pytest.ini) to make a run pass.", out)
        self.assertNotIn("Never edit", gates.retry([PYTEST | {"protect": []}], [{"gate": "pytest"}], "LOGS"))


class TestsRed(unittest.TestCase):
    def test_a_red_pass_names_its_gate(self):
        meta = {"state": "OPEN", "headRefName": "f", "headRefOid": "h" * 40, "baseRefName": "main",
                "mergeable": "MERGEABLE"}
        result = {"summary": "s", "commit_message": "", "items": [{"ref": "t", "disposition": "fixed", "reply": ""}]}
        red = [{"gate": "Karma", "ns": "a-test", "ok": False, "log": "boom"}]
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        with patch.object(fix, "sh", side_effect=lambda args, **kw: json.dumps(meta) if args[0] == "gh" else ""), \
                patch.object(fix, "load", return_value={}), patch.object(fix, "save"), \
                patch.object(fix, "checks", return_value=[]), patch.object(fix, "failed_jobs", return_value=[]), \
                patch.object(fix, "feedback", return_value=[{"ref": "t", "kind": "thread", "path": "a"}]), \
                patch.object(fix, "worktree", return_value=scratch.name), patch.object(fix, "project_conventions"), \
                patch.object(fix, "fix_prompt", return_value="p"), patch.object(fix, "changed", return_value=[]), \
                patch.object(fix.names, "SCRATCH", scratch.name), \
                patch.object(fix, "codex", return_value=("s", result)) as codex, \
                patch.object(fix.gates, "run", return_value=red):
            out = fix.run(7)
        self.assertEqual((out["status"], out["gate"], out["failing"]), ("tests-red", "Karma", ["a-test"]))
        self.assertTrue(codex.call_args.args[1].startswith("These Karma runs fail after your change:"))


if __name__ == "__main__":
    unittest.main()
