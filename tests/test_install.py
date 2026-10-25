import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class Installation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.root = self.home / "workdir/sample"
        self.root.mkdir(parents=True)
        (self.root / "SKILL.md").write_text("new skill")
        self.target = self.home / ".claude/skills/delegator/SKILL.md"
        self.target.parent.mkdir(parents=True)
        self.target.write_text("old skill")
        self.brief = self.target.parent / "briefs/task.md"
        self.brief.parent.mkdir()
        self.brief.write_text("local task")
        (self.root / "links.json").write_text(json.dumps({"links": {
            ".claude/skills/delegator/SKILL.md": "SKILL.md"}}))

    def install(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.root, self.home, **kwargs)

    def check_links_and_state(self):
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.read_text(), "new skill")
        self.assertEqual(self.brief.read_text(), "local task")
        saved = list((self.home / ".local/state/sample/backups").rglob("SKILL.md"))
        self.assertTrue(any(p.read_text() == "old skill" for p in saved))

    def test_dry_run_changes_nothing(self):
        before = sorted(str(p) for p in self.home.rglob("*"))
        self.install(dry_run=True)
        self.assertEqual(before, sorted(str(p) for p in self.home.rglob("*")))
        self.assertFalse(self.target.is_symlink())

    def test_reinstall_preserves_briefs_and_updates_through_link(self):
        self.install()
        self.install()
        self.check_links_and_state()
        (self.root / "SKILL.md").write_text("edited skill")
        self.assertEqual(self.target.read_text(), "edited skill")

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_chezmoi_apply_preserves_state_and_source(self):
        source = self.home / ".local/share/chezmoi"
        original = source / "dot_claude/skills/delegator/SKILL.md"
        original.parent.mkdir(parents=True)
        original.write_text("old skill")
        unrelated = source / "dot_claude/settings.json"
        unrelated.write_text("unrelated settings")
        with patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}):
            subprocess.run(["chezmoi", "--source", str(source), "--destination", str(self.home),
                            "apply", "--force", str(self.target)], check=True)
            self.install(chezmoi=source)
            self.install(chezmoi=source)
        self.check_links_and_state()
        self.assertEqual(unrelated.read_text(), "unrelated settings")
        managed = original.with_name("symlink_SKILL.md.tmpl")
        self.assertIn("{{ .chezmoi.homeDir }}/workdir/sample/SKILL.md", managed.read_text())
        self.assertFalse(original.exists())


class ConfigInstallation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.root = self.home / "workdir/sample"
        self.root.mkdir(parents=True)
        (self.root / "links.json").write_text(json.dumps({"links": {}, "config": ".config/pr-wizard/config.json"}))
        self.source = self.home / ".local/share/chezmoi"
        self.target = self.home / ".config/pr-wizard/config.json"
        self.real = self.source / ".pr-wizard/config.json"
        self.template = self.source / "dot_config/pr-wizard/symlink_config.json.tmpl"

    def install(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.root, self.home, **kwargs)

    def test_without_chezmoi_a_plain_file_is_seeded_once(self):
        self.install()
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(json.loads(self.target.read_text()), json.loads(installer.default_config()))
        self.target.write_text('{"fix": {"workers": 1}}')
        self.install()
        self.assertEqual(self.target.read_text(), '{"fix": {"workers": 1}}')

    def test_dry_run_writes_nothing(self):
        self.install(chezmoi=self.source, dry_run=True)
        self.assertFalse(self.source.exists() or self.target.exists())

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_chezmoi_links_the_target_to_the_real_file_and_keeps_edits(self):
        self.source.mkdir(parents=True)
        with patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}):
            self.install(chezmoi=self.source)
            self.real.write_text('{"fix": {"workers": 1}}')
            self.install(chezmoi=self.source)
        self.assertEqual(self.template.read_text(), "{{ .chezmoi.sourceDir }}/.pr-wizard/config.json\n")
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.resolve(), self.real.resolve())
        self.assertEqual(self.real.read_text(), '{"fix": {"workers": 1}}')

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_chezmoi_backs_up_a_plain_file_at_the_target(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("hand edited")
        with patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}):
            self.install(chezmoi=self.source)
        saved = list((self.home / ".local/state/sample/backups").rglob("config.json"))
        self.assertEqual([p.read_text() for p in saved], ["hand edited"])
        self.assertTrue(self.target.is_symlink())


class Requirements(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.daemon, self.shell = Path(temp.name) / "daemon", Path(temp.name) / "shell"
        self.daemon.mkdir()
        self.shell.mkdir()

    def tools(self, shell=(), failing=()):
        for tool in installer.TOOLS:
            path = (self.shell if tool in shell else self.daemon) / tool
            path.write_text(f"#!/bin/sh\nexit {int(tool in failing)}\n")
            path.chmod(0o755)

    def problems(self):
        with patch.dict(os.environ, {"PATH": str(self.shell)}):
            return list(installer.problems(str(self.daemon), app=False))

    def test_every_tool_on_the_daemon_path_passes(self):
        self.tools()
        self.assertEqual(self.problems(), [])

    def test_a_tool_on_the_shell_path_only_names_the_link(self):
        self.tools(shell=["codex"])
        self.assertEqual(self.problems(),
                         [f"codex is off the daemon PATH: mkdir -p ~/.local/bin && ln -s {self.shell}/codex ~/.local/bin/"])

    def test_a_missing_tool_names_its_install(self):
        self.tools()
        (self.daemon / "claude").unlink()
        self.assertEqual(self.problems(), ["claude is missing: https://claude.com/claude-code"])

    def test_old_python_and_logged_out_gh(self):
        self.tools(failing=["python3", "gh"])
        self.assertEqual(self.problems(), [f"{self.daemon}/python3 is older than 3.10: brew install python",
                                           "gh is not logged in: gh auth login"])


if __name__ == "__main__":
    unittest.main()
