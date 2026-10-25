"""Every engine argv the two scripts build. The goldens are today's literal commands: with no config file
and with the seeded file (`config.DEFAULTS` dumped) they must stay byte for byte the same."""
import contextlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_wizard import config
from prs import pr_fix, pr_review  # noqa: F401  (puts review/ on sys.path and pins the config path)

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
            contextlib.redirect_stderr(open(os.devnull, "w")):
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
                    render.assert_called_once_with(f"{reviewer}.md", sc)
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


if __name__ == "__main__":
    unittest.main()
