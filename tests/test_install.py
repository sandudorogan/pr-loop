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


if __name__ == "__main__":
    unittest.main()
