import json
import os
from pathlib import Path
import plistlib
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import prs  # noqa: F401
from pr_wizard import db, names

ROOT = Path(__file__).resolve().parents[1]
GITOPS = "iprally/gitops"
STATE = Path.home() / ".local/state"


def script_names(script, **env):
    probe = ("import json, runpy, sys; g = runpy.run_path(sys.argv[1]); "
             "print(json.dumps({k: g.get(k) for k in ('REPO', 'REPO_ROOT', 'BRIEFS')}))")
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("IPR_", "PR_WIZARD_REPO"))}
    out = subprocess.run([sys.executable, "-c", probe, str(script)], env={**clean, **env}, cwd="/",
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class RunnerPaths(unittest.TestCase):
    def test_review_resources_resolve_through_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            for source in (ROOT / "review/pr_review.py", ROOT / "review/pr_fix.py"):
                link = Path(temporary) / source.name
                link.symlink_to(source)
                direct, linked = runpy.run_path(str(source)), runpy.run_path(str(link))
                for name in ("SCHEMA", "PROMPTS", "PROMPT", "MERGE_PROMPT"):
                    if name in direct:
                        self.assertEqual(direct[name], linked[name])
                        self.assertTrue(Path(linked[name]).exists(), linked[name])

    def test_queue_finds_the_review_scripts(self):
        self.assertEqual(Path(names.PR_REVIEW), ROOT / "review/pr_review.py")
        self.assertEqual(Path(names.PR_FIX), ROOT / "review/pr_fix.py")

    def test_both_cli_names_run_through_a_symlink_chain(self):
        self.assertEqual(os.readlink(ROOT / "bin/review-queue"), "pr-wizard")
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("review-queue", "pr-wizard"):
                link = Path(temporary) / name
                link.symlink_to(ROOT / "bin" / name)
                out = subprocess.run([str(link), "-h"], cwd=temporary, capture_output=True, text=True, check=True)
                self.assertIn("--daemon", out.stdout)

    def test_both_cli_names_are_installed(self):
        links = json.loads((ROOT / "links.json").read_text())["links"]
        self.assertEqual(links[".local/bin/review-queue"], "bin/review-queue")
        self.assertEqual(links[".local/bin/pr-wizard"], "bin/pr-wizard")

    def test_scripts_take_repo_and_paths_from_names(self):
        for script in ("pr_review.py", "pr_fix.py"):
            with tempfile.TemporaryDirectory() as temporary:
                link = Path(temporary) / script
                link.symlink_to(ROOT / "review" / script)
                default = script_names(link)
                gitops = script_names(link, IPR_REPO=GITOPS, IPR_REPO_ROOT="/tmp/gitops")
                wizard = script_names(link, PR_WIZARD_REPO=GITOPS, PR_WIZARD_REPO_ROOT="/tmp/gitops",
                                      IPR_REPO=names.MONOREPO, IPR_REPO_ROOT="/tmp/iprally")
            self.assertEqual((default["REPO"], default["REPO_ROOT"]), (names.MONOREPO, str(Path.home() / "workdir/iprally")))
            self.assertEqual((gitops["REPO"], gitops["REPO_ROOT"]), (GITOPS, "/tmp/gitops"))
            self.assertEqual((wizard["REPO"], wizard["REPO_ROOT"]), (GITOPS, "/tmp/gitops"))
            if script == "pr_review.py":
                self.assertEqual(Path(default["BRIEFS"]), Path.home() / ".claude/skills/delegator/briefs")

    def test_names_carry_the_pr_wizard_paths(self):
        self.assertEqual(names.LABEL, "local.pr-wizard")
        self.assertEqual(names.LOG, str(Path.home() / "Library/Logs/pr-wizard.log"))
        self.assertEqual(names.DAEMON_LOCK, str(STATE / "pr-wizard/daemon.lock"))
        self.assertEqual(names.DAEMON_PID, str(STATE / "pr-wizard/daemon.pid"))
        self.assertEqual(names.root(GITOPS), str(Path.home() / "workdir/gitops"))
        self.assertEqual(db.DB, names.DB)
        self.assertEqual(names.DB, str(STATE / "pr-wizard/state.db"))
        self.assertEqual(names.SCRATCH, str(STATE / "pr-wizard/scratch"))
        self.assertEqual(names.slot(1), str(STATE / "pr-wizard/slot.1.lock"))
        self.assertEqual(names.lock(GITOPS, 7, ".fix"), str(STATE / "pr-wizard/locks/iprally/gitops/7.fix"))

    def test_schema_and_launchd_templates_parse(self):
        for schema in (ROOT / "review").glob("*.json"):
            self.assertIsInstance(json.loads(schema.read_text()), dict)
        for template in (ROOT / "launchd").glob("*.tmpl"):
            data = plistlib.loads(template.read_text().replace("{{ .chezmoi.homeDir }}", str(Path.home())).encode())
            self.assertEqual(data["ProgramArguments"][0], str(Path.home() / ".local/bin/pr-wizard"))
            self.assertEqual({data["StandardOutPath"], data["StandardErrorPath"]}, {names.LOG})
            self.assertNotIn("IPR_REPO", data.get("EnvironmentVariables", {}))

    def test_the_daemon_is_the_only_launchd_job(self):
        plists = [plistlib.loads(t.read_bytes()) for t in (ROOT / "launchd").glob("*.tmpl")]
        self.assertEqual([p["Label"] for p in plists], [names.LABEL])
        self.assertEqual(plists[0]["ProcessType"], "Standard")
        self.assertIn("/usr/sbin", plists[0]["EnvironmentVariables"]["PATH"].split(":"))
        templates = json.loads((ROOT / "links.json").read_text())["templates"]
        self.assertEqual(templates, {"Library/LaunchAgents/local.pr-wizard.plist": "launchd/local.pr-wizard.plist.tmpl"})

    def test_the_cli_kickstarts_the_label_the_daemon_wrote(self):
        from pr_wizard import cli
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(names, "LABEL_FILE", f"{temporary}/launchd-label"), \
                patch.object(cli.subprocess, "run") as run:
            cli.start()
            Path(names.LABEL_FILE).write_text("local.review-queue\n")
            cli.start()
        self.assertEqual([c.args[0][-1].rsplit("/", 1)[1] for c in run.call_args_list],
                         ["local.pr-wizard", "local.review-queue"])

    def test_the_label_file_names_the_launchd_job(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(names, "LABEL_FILE", f"{temporary}/launchd-label"):
            names.write_label()
            self.assertEqual(Path(names.LABEL_FILE).read_text(), "local.pr-wizard\n")


if __name__ == "__main__":
    unittest.main()
