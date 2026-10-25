import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prs import pr_fix, pr_review as prr
from pr_wizard import conventions as cv

SKILL = "---\nname: {name}\ndescription: {description}\n---\n\n# Steps\n"


class Checkout(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = os.path.realpath(self.dir.name)

    def write(self, rel, text):
        path = Path(self.root, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def collect(self, *changed):
        return cv.collect(self.root, list(changed))


class Sources(Checkout):
    def test_every_source_in_order(self):
        for rel, text in (("AGENTS.md", "root agents"), ("CLAUDE.md", "root claude"), ("ui/AGENTS.md", "ui agents"),
                          ("CONTRIBUTING.md", "contrib"), (".editorconfig", "[*]\nindent_size = 2"),
                          (".prettierrc.json", "{}"), (".agents/skills/adr/SKILL.md",
                                                       SKILL.format(name="adr", description="Write an ADR."))):
            self.write(rel, text)
        conv = self.collect("ui/src/a.cljs")
        self.assertEqual(conv.files, ["AGENTS.md", "CLAUDE.md", "ui/AGENTS.md", "CONTRIBUTING.md", ".editorconfig",
                                      ".prettierrc.json"])
        order = [conv.text.index(f"### {p}") for p in conv.files]
        self.assertEqual(order, sorted(order))
        self.assertIn("- adr — Write an ADR. (`.agents/skills/adr/SKILL.md`)", conv.text)
        self.assertTrue(conv.text.startswith("<conventions>\n") and conv.text.endswith("\n</conventions>"))

    def test_contributing_takes_the_first_place_it_finds(self):
        self.write(".github/CONTRIBUTING.md", "github")
        self.write("docs/CONTRIBUTING.md", "docs")
        self.assertEqual(self.collect().files, [".github/CONTRIBUTING.md"])

    def test_nested_agent_files_closest_first_per_changed_path(self):
        for rel in ("api/AGENTS.md", "api/test/AGENTS.md", "api/test/CLAUDE.md", "ui/AGENTS.md", "docs/AGENTS.md"):
            self.write(rel, rel)
        conv = self.collect("api/test/x_test.clj", "ui/src/a.cljs", "api/src/y.clj")
        self.assertEqual(conv.files, ["api/test/AGENTS.md", "api/test/CLAUDE.md", "api/AGENTS.md", "ui/AGENTS.md"])

    def test_skills_are_listed_once_through_a_symlinked_dir(self):
        self.write(".agents/skills/q/SKILL.md", "---\nname: q\ndescription: >\n  Two\n  lines.\n---\n")
        os.makedirs(os.path.join(self.root, ".claude"))
        os.symlink("../.agents/skills", os.path.join(self.root, ".claude", "skills"))
        conv = self.collect()
        self.assertEqual(conv.skills, [{"name": "q", "description": "Two lines.", "path": ".agents/skills/q/SKILL.md"}])
        self.assertEqual((conv.files, conv.none), ([], False))


class Includes(Checkout):
    def test_at_agents_md_is_not_repeated(self):
        self.write("AGENTS.md", "the rules")
        self.write("CLAUDE.md", "@AGENTS.md\n")
        self.write("ui/AGENTS.md", "ui rules")
        self.write("ui/CLAUDE.md", "@AGENTS.md\n")
        conv = self.collect("ui/a.cljs")
        self.assertEqual(conv.text.count("the rules"), 1)
        self.assertEqual(conv.text.count("ui rules"), 1)
        self.assertNotIn("### CLAUDE.md", conv.text)
        self.assertEqual(conv.files, ["AGENTS.md", "CLAUDE.md", "ui/AGENTS.md", "ui/CLAUDE.md"])

    def test_an_include_expands_in_place_relative_to_its_file(self):
        self.write("CLAUDE.md", "before\n@docs/style.md\nafter")
        self.write("docs/style.md", "style\n@more.md")
        self.write("docs/more.md", "more")
        conv = self.collect()
        self.assertIn("before\nstyle\nmore\nafter", conv.text)
        self.assertEqual(conv.files, ["CLAUDE.md", "docs/style.md", "docs/more.md"])

    def test_home_and_outside_includes_are_dropped(self):
        self.write("CLAUDE.md", "@~/AGENTS.md\n@../outside.md\nkept")
        Path(self.root).parent.joinpath("outside.md").write_text("secret")
        self.addCleanup(Path(self.root).parent.joinpath("outside.md").unlink)
        conv = self.collect()
        self.assertIn("### CLAUDE.md\n\nkept\n", conv.text)
        self.assertNotIn("secret", conv.text)
        self.assertEqual(conv.files, ["CLAUDE.md"])

    def test_a_cycle_includes_each_file_once(self):
        self.write("CLAUDE.md", "c\n@a.md")
        self.write("a.md", "a\n@b.md")
        self.write("b.md", "b\n@a.md\n@CLAUDE.md")
        self.assertIn("c\na\nb\n", self.collect().text)

    def test_includes_stop_three_levels_deep(self):
        self.write("CLAUDE.md", "@1.md")
        for n in range(1, 5):
            self.write(f"{n}.md", f"level {n}\n@{n + 1}.md")
        text = self.collect().text
        self.assertIn("level 3", text)
        self.assertNotIn("level 4", text)


class Configs(Checkout):
    def test_small_configs_inline_and_large_ones_list(self):
        self.write(".cljfmt.edn", "{:indents {}}")
        self.write(".clj-kondo/config.edn", "x" * (cv.INLINE_CONFIG + 1))
        conv = self.collect()
        self.assertIn("### .cljfmt.edn\n\n{:indents {}}", conv.text)
        self.assertNotIn("### .clj-kondo/config.edn", conv.text)
        self.assertIn("Formatter and linter configs, read when they apply: `.clj-kondo/config.edn`", conv.text)
        self.assertEqual(conv.files, [".cljfmt.edn", ".clj-kondo/config.edn"])

    def test_pyproject_keeps_only_the_formatter_tables(self):
        self.write("pyproject.toml", '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 120\n[tool.ruff.lint]\n'
                                     'select = ["E"]\n[tool.poetry]\nname = "x"\n')
        text = self.collect().text
        self.assertIn('[tool.ruff]\nline-length = 120\n[tool.ruff.lint]\nselect = ["E"]\n</conventions>', text)
        self.assertNotIn("poetry", text)

    def test_pyproject_without_those_tables_is_no_source(self):
        self.write("pyproject.toml", '[project]\nname = "x"\n')
        self.assertTrue(self.collect().none)


class Caps(Checkout):
    def test_a_long_document_is_cut_at_the_document_cap(self):
        self.write("AGENTS.md", "a" * (cv.DOC_CAP + 10))
        text = self.collect().text
        self.assertIn("a" * cv.DOC_CAP + "\n[… truncated: read AGENTS.md for the rest]", text)
        self.assertNotIn("a" * (cv.DOC_CAP + 1), text)

    def test_past_the_total_cap_sources_are_listed_by_path(self):
        self.write("AGENTS.md", "a" * cv.DOC_CAP)
        self.write("CLAUDE.md", "c" * cv.DOC_CAP)
        self.write("ui/AGENTS.md", "u" * cv.DOC_CAP)
        self.write(".editorconfig", "root = true")
        self.write(".agents/skills/s/SKILL.md", SKILL.format(name="s", description="Long help."))
        text = self.collect("ui/a.cljs").text
        left = cv.TOTAL_CAP - 2 * cv.DOC_CAP
        self.assertIn("\n" + "u" * left + "\n[… truncated: read ui/AGENTS.md for the rest]", text)
        self.assertIn("Over the size cap, read when they apply: `.editorconfig`", text)
        self.assertIn("- `.agents/skills/s/SKILL.md`", text)
        self.assertNotIn("Long help.", text)


class NoneFound(Checkout):
    def test_the_none_text(self):
        conv = self.collect("a.py")
        self.assertEqual((conv.none, conv.files, conv.skills), (True, [], []))
        self.assertEqual(conv.text, '<conventions none="true">This project documents no conventions. Judge the change '
                                    'against the code around it, and report no convention findings.</conventions>')


class Names(Checkout):
    def git(self, *args):
        subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)

    def test_tree_names_at_a_ref(self):
        for rel in ("AGENTS.md", "CLAUDE.md", "ui/AGENTS.md", "api/test/CLAUDE.md", "a/b/c/AGENTS.md",
                    ".editorconfig", ".clj-kondo/config.edn", ".agents/skills/adr/SKILL.md",
                    ".agents/skills/adr/ref.md", "pyproject.toml"):
            self.write(rel, '[project]\nname = "x"\n' if rel == "pyproject.toml" else "x")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.write("CONTRIBUTING.md", "not committed")
        self.assertEqual(cv.names(self.root, "HEAD"), {
            "ref": "HEAD", "files": ["AGENTS.md", "CLAUDE.md", "api/test/CLAUDE.md", "ui/AGENTS.md", ".editorconfig",
                                     ".clj-kondo/config.edn"], "skills": ["adr"]})


IPRALLY = (("AGENTS.md", "Read docs/tech/ first."), ("CLAUDE.md", "@AGENTS.md\n"),
           (".agents/skills/quality-self-review/SKILL.md",
            SKILL.format(name="quality-self-review", description="Self-review against the convention docs.")))
SC = {"pr": 7, "branch": "f", "head": "h" * 40, "base_ref": "origin/main", "diff_range": "origin/main...h",
      "round_note": "round 1"}


class Prompts(Checkout):
    def quality(self):
        return prr.render("quality.md", dict(SC, conventions=self.collect("ui/a.cljs")))

    def test_the_iprally_quality_prompt_points_at_its_skill(self):
        for rel, text in IPRALLY:
            self.write(rel, text)
        prompt = self.quality()
        self.assertIn("Read `.agents/skills/quality-self-review/SKILL.md` in this checkout and follow its steps", prompt)
        self.assertIn("Read docs/tech/ first.", prompt)
        self.assertNotIn("{", prompt.split("<output>")[0].replace("{SCHEMA}", ""))

    def test_without_the_skill_the_quality_prompt_never_names_it(self):
        self.write("AGENTS.md", "rules")
        prompt = self.quality()
        self.assertNotIn("quality-self-review/SKILL.md", prompt)
        self.assertNotIn("{SKILL", prompt)
        self.assertIn("Review against the rules in the `<conventions>` block", prompt)

    def test_no_prompt_names_iprally_paths_or_tools(self):
        for name in ("opus.md", "codex.md", "quality.md", "fix.md", "merge.md"):
            text = Path(prr.PROMPTS, name).read_text()
            with self.subTest(name):
                self.assertIn("{CONVENTIONS}", text)
                for word in ("docs/tech", "ui/docs", "api/docs", "cljs-patrol", ".agents/skills", "origin/main"):
                    self.assertNotIn(word, text)

    def test_the_fix_and_merge_prompts_carry_the_block(self):
        self.write("AGENTS.md", "fix rules")
        conv = self.collect()
        meta = {"headRefName": "f", "headRefOid": "h" * 40, "baseRefName": "main"}
        for prompt in (pr_fix.fix_prompt(7, meta, "/s/feedback.json", conv),
                       pr_fix.merge_prompt(7, meta, ["a.py"], conv)):
            self.assertIn("<conventions>\n### AGENTS.md\n\nfix rules\n</conventions>", prompt)
            self.assertNotIn("{CONVENTIONS}", prompt)


class QualitySkip(Checkout):
    def run_main(self, reviewer, dry_run=False):
        sc = dict(SC, head="c" * 40, round=2, done_at_head=[], clean_at_head=[])
        out = io.StringIO()
        argv = ["pr_review.py", "run", "--pr", "7", "--reviewer", reviewer, *(["--dry-run"] if dry_run else [])]
        with patch("sys.argv", argv), patch.object(prr, "scope", return_value=sc), \
                patch.object(prr.names, "migrate"), patch.object(prr, "review_worktree", return_value=self.root), \
                patch.object(prr, "changed", return_value=["a.py"]), patch.object(prr.db, "add_clean") as clean, \
                patch.object(prr, "commentable_lines", return_value={}), \
                patch.object(prr, "run_reviewer", return_value=("claude", {"findings": []})) as engine, \
                contextlib.redirect_stdout(out):
            prr.main()
        return json.loads(out.getvalue()), clean, engine

    def test_a_reviewer_that_needs_conventions_skips_a_project_without_them(self):
        res, clean, engine = self.run_main("quality")
        self.assertEqual(res, {"reviewer": "quality", "round": 2, "posted": False, "stop": True,
                               "reason": "no-conventions", "conventions": []})
        clean.assert_called_once_with(prr.REPO, "7", "c" * 40, "quality")
        engine.assert_not_called()

    def test_a_dry_run_skip_records_nothing(self):
        _, clean, _ = self.run_main("quality", dry_run=True)
        clean.assert_not_called()

    def test_other_reviewers_still_run_and_report_the_files(self):
        res, _, engine = self.run_main("opus")
        engine.assert_called_once()
        self.assertEqual((res["reason"], res["conventions"]), ("no-findings", []))

    def test_with_conventions_quality_runs_and_reports_them(self):
        self.write("AGENTS.md", "rules")
        res, _, engine = self.run_main("quality")
        engine.assert_called_once()
        self.assertEqual(res["conventions"], ["AGENTS.md"])
        self.assertIn("### AGENTS.md", engine.call_args[0][2]["conventions"].text)


if __name__ == "__main__":
    unittest.main()
