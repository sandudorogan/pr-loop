import json
from pathlib import Path
import plistlib
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RunnerPaths(unittest.TestCase):
    def test_queue_and_review_resources_resolve_through_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            for source in (ROOT / "bin/review-queue", ROOT / "review/pr_review.py", ROOT / "review/pr_fix.py"):
                link = Path(temporary) / source.name
                link.symlink_to(source)
                direct, linked = runpy.run_path(str(source)), runpy.run_path(str(link))
                for name in ("PR_REVIEW", "PR_FIX", "SCHEMA", "PROMPTS", "PROMPT", "MERGE_PROMPT"):
                    if name in direct:
                        self.assertEqual(direct[name], linked[name])
                        self.assertTrue(Path(linked[name]).exists(), linked[name])
                if "BRIEFS" in linked:
                    self.assertEqual(Path(linked["BRIEFS"]), Path.home() / ".claude/skills/delegator/briefs")
                    self.assertEqual(Path(linked["CLEAN_CACHE"]).parent, Path.home() / ".claude/skills/delegator")

    def test_schema_and_launchd_templates_parse(self):
        for schema in (ROOT / "review").glob("*.json"):
            self.assertIsInstance(json.loads(schema.read_text()), dict)
        for template in (ROOT / "launchd").glob("*.tmpl"):
            data = plistlib.loads(template.read_text().replace("{{ .chezmoi.homeDir }}", str(Path.home())).encode())
            self.assertEqual(data["ProgramArguments"][0], str(Path.home() / ".local/bin/review-queue"))
            self.assertNotIn("IPR_REPO", data.get("EnvironmentVariables", {}))

    def test_the_daemon_is_the_only_launchd_job(self):
        plists = [plistlib.loads(t.read_bytes()) for t in (ROOT / "launchd").glob("*.tmpl")]
        self.assertEqual([p["Label"] for p in plists], ["local.review-queue"])
        self.assertEqual(plists[0]["ProcessType"], "Standard")
        self.assertIn("/usr/sbin", plists[0]["EnvironmentVariables"]["PATH"].split(":"))
        templates = json.loads((ROOT / "links.json").read_text())["templates"]
        self.assertEqual(list(templates.values()), ["launchd/local.review-queue.plist.tmpl"])


if __name__ == "__main__":
    unittest.main()
