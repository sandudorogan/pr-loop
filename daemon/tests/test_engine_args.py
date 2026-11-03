"""Every engine argv the two scripts build. The goldens are today's literal commands: with no config file
and with the seeded file (`config.DEFAULTS` dumped) they must stay byte for byte the same."""
import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_wizard import config
import prs  # noqa: F401  (puts review/ on sys.path and pins the config path)

SCHEMA, LAST = "<SCHEMA>", "<LAST>"
SANDBOX = ["-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"',
           "-c", 'sandbox_workspace_write.writable_roots=["/wt", "/wt/.git", "<SCRATCH>"]']
IO = ["--json", "--output-schema", SCHEMA, "-o", "<SCRATCH>/last.json"]
FIX_NEW = ["codex", "exec", "-C", "/wt", *SANDBOX, *IO, "PROMPT"]
FIX_RESUMED = ["codex", "exec", "resume", *SANDBOX, *IO, "SESSION", "PROMPT"]


def claude(model, effort=None):
    return ["claude", "-p", "PROMPT", "--model", model, "--disallowedTools", "Edit,Write,NotebookEdit",
            "--output-format", "text", *(["--effort", effort] if effort else [])]


CODEX = ["codex", "exec", "-C", "/wt", "-s", "read-only", "--output-schema", SCHEMA, "--output-last-message", LAST,
         "PROMPT"]

# reviewer -> (full round, incremental round, the other engine's argv at the usage limit)
REVIEW_GOLDENS = {
    "opus": (claude("opus", "high"), claude("opus", "medium"), CODEX),
    "codex": (CODEX, CODEX, claude("opus")),
    "quality": (claude("haiku", "xhigh"), claude("haiku", "xhigh"), CODEX),
}


@contextlib.contextmanager
def scripts(doc=None):
    """pr_review and pr_fix imported fresh, as a run does, against a config file holding `doc` (none = no file)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        if doc is not None:
            Path(path).write_text(json.dumps(doc))
        saved = {n: sys.modules.pop(n, None) for n in ("pr_review", "pr_fix")}
        with patch.dict(os.environ, {"PR_WIZARD_CONFIG": path, "IPR_REPO": "iprally/iprally"}):
            fresh = importlib.import_module("pr_review"), importlib.import_module("pr_fix")
        try:
            yield fresh
        finally:
            for name, module in saved.items():
                sys.modules.pop(name, None)
                module is None or sys.modules.__setitem__(name, module)


def fake_run(calls, at_limit=0):
    """A subprocess.run that records each call, hits the usage limit on the first `at_limit` ones, and writes
    the file an engine would write."""
    def run(args, **kw):
        calls.append((list(args), {k: kw[k] for k in ("cwd", "timeout") if k in kw}))
        if len(calls) <= at_limit:
            return subprocess.CompletedProcess(args, 1, "", "you hit your usage limit")
        for flag, body in (("--output-last-message", '{"findings": []}'), ("-o", '{"items": []}')):
            if flag in args:
                Path(args[args.index(flag) + 1]).write_text(body)
        return subprocess.CompletedProcess(args, 0, '{"findings": []}\n{"type": "thread.started", "thread_id": "T"}', "")
    return run


def review(prr, reviewer, incremental=False, at_limit=False):
    """(engine that answered, argv of every engine call, kwargs of each, the render mock)."""
    calls = []
    with patch.object(prr, "render", return_value="PROMPT") as render, \
            patch.object(prr.subprocess, "run", fake_run(calls, int(at_limit))), \
            contextlib.redirect_stderr(io.StringIO()):
        engine, _ = prr.run_reviewer(reviewer, "/wt", {"base_sha": "b" * 40 if incremental else None})
    shown = lambda a: SCHEMA if a == prr.SCHEMA else LAST if "/" in a and a.endswith(".json") else a
    return engine, [[shown(a) for a in argv] for argv, _ in calls], [kw for _, kw in calls], render


def fix_turn(fix, session=None):
    scratch = tempfile.mkdtemp()
    calls = []
    with patch.object(fix, "sh", return_value=".git"), patch.object(fix.subprocess, "run", fake_run(calls)):
        fix.codex("/wt", "PROMPT", session, scratch)
    argv, kw = calls[0]
    return [a.replace(fix.SCHEMA, SCHEMA).replace(scratch, "<SCRATCH>") for a in argv], kw


class Goldens:
    """Each subclass runs the same goldens against one way of supplying the defaults."""
    scripts_doc = None

    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.prr, self.fix = stack.enter_context(scripts(self.scripts_doc))

    def test_every_reviewer_round_and_engine(self):
        for reviewer, (full, incremental, other) in REVIEW_GOLDENS.items():
            for is_incremental, primary in ((False, full), (True, incremental)):
                with self.subTest(reviewer=reviewer, incremental=is_incremental):
                    sc = {"base_sha": "b" * 40 if is_incremental else None}
                    engine, argvs, kws, render = review(self.prr, reviewer, is_incremental)
                    self.assertEqual((engine, argvs), (primary[0], [primary]))
                    self.assertEqual([kw["timeout"] for kw in kws], [2700])
                    render.assert_called_once_with(f"{reviewer}.md", sc, "/wt")
                    engine, argvs, kws, _ = review(self.prr, reviewer, is_incremental, at_limit=True)
                    self.assertEqual((engine, argvs), (other[0], [primary, other]))
                    self.assertEqual([kw["timeout"] for kw in kws], [2700, 2700])

    def test_the_fixer_turns(self):
        self.assertEqual(fix_turn(self.fix), (FIX_NEW, {"cwd": "/wt", "timeout": 2700}))
        self.assertEqual(fix_turn(self.fix, "SESSION"), (FIX_RESUMED, {"cwd": "/wt", "timeout": 2700}))

    def test_the_knobs_are_todays_constants(self):
        fix = self.fix
        self.assertEqual((fix.TIMEOUT, fix.TEST_RETRIES, fix.CI_TRIES), (2700, 2, 3))
        self.assertEqual((fix.PROMPT, fix.MERGE_PROMPT),
                         tuple(os.path.join(fix.DIR, "prompts", n) for n in ("fix.md", "merge.md")))


class NoConfigFile(Goldens, unittest.TestCase):
    scripts_doc = None


class SeededFile(Goldens, unittest.TestCase):
    """What unit 24 writes to ~/.config/pr-wizard/config.json: the defaults, dumped."""
    scripts_doc = json.loads(json.dumps(config.DEFAULTS))


def project(review=None, fix=None, repo="iprally/iprally"):
    """A config file doc with a project override."""
    return {"projects": {repo: {**({"review": review} if review else {}), **({"fix": fix} if fix else {})}}}


BUGBOT = {"id": "bugbot", "label": "Grok 4.7 · Cursor Bugbot", "prompt": "bugbot.md", "engine": "cursor",
          "fallback": False, "cursor": {"model": "grok-4.7-medium"}}
CURSOR = ["cursor-agent", "-p", "--trust", "--mode", "ask", "--workspace", "/wt", "--output-format", "text",
          "--model", "grok-4.7-medium", "PROMPT"]


def reviewers(**edits):
    """The default reviewers, each with the `edits[id]` merged over it."""
    return [config.merge(r, edits.get(r["id"], {})) for r in config.DEFAULTS["review"]["reviewers"]]


class ProjectOverride(unittest.TestCase):
    def scripts(self, doc):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        return stack.enter_context(scripts(doc))

    def test_a_project_changes_a_reviewer_model_and_effort(self):
        prr, _ = self.scripts(project(review={"reviewers": reviewers(
            opus={"claude": {"model": "sonnet", "effort": "low", "incremental": {"model": "haiku", "effort": None}}},
            quality={"claude": {"model": "opus", "effort": None}})}))
        self.assertEqual(review(prr, "opus")[1], [claude("sonnet", "low")])
        self.assertEqual(review(prr, "opus", incremental=True)[1], [claude("haiku")])
        self.assertEqual(review(prr, "quality", incremental=True)[1], [claude("opus")])
        self.assertEqual(review(prr, "codex")[1], [CODEX])

    def test_a_project_for_another_repo_changes_nothing(self):
        prr, fix = self.scripts(project(review={"timeout_s": 60}, fix={"model": "x"}, repo="iprally/gitops"))
        self.assertEqual(review(prr, "opus")[1:3], ([claude("opus", "high")], [{"cwd": "/wt", "timeout": 2700}]))
        self.assertEqual(fix_turn(fix)[0], FIX_NEW)

    def test_codex_model_and_effort_reach_the_review_argv(self):
        prr, _ = self.scripts(project(review={"reviewers": reviewers(
            codex={"codex": {"model": "gpt-9", "effort": "high"}}, opus={"codex": {"model": "gpt-8", "effort": None}})}))
        flags = ["-c", 'model="gpt-9"', "-c", 'model_reasoning_effort="high"']
        self.assertEqual(review(prr, "codex")[1], [CODEX[:-1] + flags + ["PROMPT"]])
        engine, argvs, *_ = review(prr, "opus", at_limit=True)
        self.assertEqual((engine, argvs[1]), ("codex", CODEX[:-1] + ["-c", 'model="gpt-8"', "PROMPT"]))

    def test_no_fallback_stops_at_the_primary_engine(self):
        prr, _ = self.scripts(project(review={"reviewers": reviewers(opus={"fallback": False})}))
        calls = []
        with patch.object(prr, "render", return_value="PROMPT"), patch.object(prr.subprocess, "run", fake_run(calls, 1)), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            prr.run_reviewer("opus", "/wt", {"base_sha": None})
        self.assertEqual([c[0][0] for c in calls], ["claude"])

    def test_bugbot_runs_cursor_agent_read_only_in_the_worktree(self):
        prr, _ = self.scripts(project(review={"reviewers": [*reviewers(), BUGBOT]}))
        engine, argvs, kws, _ = review(prr, "bugbot")
        self.assertEqual((engine, argvs, kws), ("cursor", [CURSOR], [{"cwd": "/wt", "timeout": 2700}]))

    def test_bugbot_at_its_limit_stops_without_a_fallback(self):
        prr, _ = self.scripts(project(review={"reviewers": [*reviewers(), BUGBOT]}))
        calls, err = [], io.StringIO()
        with patch.object(prr, "render", return_value="PROMPT"), patch.object(prr.subprocess, "run", fake_run(calls, 1)), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            prr.run_reviewer("bugbot", "/wt", {"base_sha": None})
        self.assertEqual([c[0][0] for c in calls], ["cursor-agent"])
        self.assertIn("cursor is at its usage limit", err.getvalue())

    def test_the_bugbot_prompt_carries_the_skill_shape(self):
        prr, _ = self.scripts(None)
        sc = {"pr": 7, "branch": "f", "head": "c" * 40, "base_ref": "origin/main", "diff_range": "origin/main...HEAD",
              "round_note": "Round 1.", "conventions": prr.conventions.collect("/nonexistent", [])}
        text = prr.render("bugbot.md", sc, "/wt")
        self.assertTrue(text.startswith("/review-bugbot\nFull Repository Path: /wt\nDiff: branch changes\n"
                                        "Base Branch: origin/main\n"))
        self.assertEqual(re.findall(r"\{[A-Z_]+\}", text), [])

    def test_the_label_and_prompt_come_from_the_config(self):
        prr, _ = self.scripts(project(review={"reviewers": reviewers(opus={"label": "Opus X", "prompt": "codex.md"})}))
        _, _, _, render = review(prr, "opus")
        render.assert_called_once_with("codex.md", {"base_sha": None}, "/wt")
        self.assertEqual(prr.REVIEWERS["opus"]["label"], "Opus X")

    def test_review_timeout_reaches_every_engine_call(self):
        prr, _ = self.scripts(project(review={"timeout_s": 123}))
        self.assertEqual(review(prr, "opus", at_limit=True)[2], [{"cwd": "/wt", "timeout": 123}, {"timeout": 123}])

    def test_a_disabled_reviewer_does_not_block_settled(self):
        prr, _ = self.scripts(project(review={"reviewers": reviewers(codex={"enabled": False})}))
        meta = {"number": 5, "state": "OPEN", "headRefName": "f", "headRefOid": "c" * 40, "baseRefName": "main",
                "title": "T", "isDraft": False}
        with patch.object(prr, "pr_meta", return_value=meta), patch.object(prr, "gh_json", return_value=[]), \
                patch.object(prr, "cleared", return_value=["opus", "quality"]):
            self.assertTrue(prr.scope(5)["settled"])
        self.assertEqual(sorted(prr.REVIEWERS), ["codex", "opus", "quality"])

    def test_the_fixer_model_effort_and_timeout(self):
        _, fix = self.scripts(project(fix={"model": "gpt-9", "effort": "high", "turn_timeout_s": 99}))
        flags = ["-c", 'model="gpt-9"', "-c", 'model_reasoning_effort="high"']
        new, resumed = fix_turn(fix), fix_turn(fix, "SESSION")
        self.assertEqual(new, (FIX_NEW[:-len(IO) - 1] + flags + FIX_NEW[-len(IO) - 1:], {"cwd": "/wt", "timeout": 99}))
        self.assertEqual(resumed[0], FIX_RESUMED[:-len(IO) - 2] + flags + FIX_RESUMED[-len(IO) - 2:])
        self.assertEqual(fix.TIMEOUT, 99)

    def test_the_fixer_prompts_and_budgets(self):
        _, fix = self.scripts(project(fix={"prompt": "opus.md", "merge_prompt": "quality.md", "test_retries": 0,
                                           "ci_tries": 7}))
        self.assertEqual((fix.PROMPT, fix.MERGE_PROMPT, fix.TEST_RETRIES, fix.CI_TRIES),
                         (os.path.join(fix.DIR, "prompts", "opus.md"), os.path.join(fix.DIR, "prompts", "quality.md"), 0, 7))
        red = [{"name": "build", "conclusion": "failure"}]
        self.assertEqual(fix.stuck(red, {"ci_tries": {"build": ["a"] * 6}}), [])
        self.assertEqual(fix.stuck(red, {"ci_tries": {"build": ["a"] * 7}}), ["build"])

    def test_ci_apps_pick_the_check_runs_that_count(self):
        runs = [[{"check_runs": [{"name": n, "app": {"slug": slug}} for n, slug in
                                 (("build", "github-actions"), ("deploy", "circleci"), ("lint", "other"))]}]]
        for apps, kept in ((["github-actions"], ["build"]), (["github-actions", "circleci"], ["build", "deploy"]), ([], [])):
            _, fix = self.scripts(project(fix={"ci_apps": apps}))
            with patch.object(fix, "gh", return_value=runs[0]):
                self.assertEqual([c["name"] for c in fix.checks("sha")], kept)

    def test_a_broken_file_runs_on_the_defaults_and_says_so(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            prr, fix = self.scripts({"review": {"timeout_s": "soon"}})
        self.assertIn("running on the defaults", err.getvalue())
        self.assertEqual((prr.TIMEOUT, fix.TIMEOUT), (2700, 2700))


if __name__ == "__main__":
    unittest.main()
