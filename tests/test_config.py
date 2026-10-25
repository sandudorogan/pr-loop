import copy
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from pr_wizard import config as c

ROOT = Path(__file__).resolve().parents[1]


def doc(**changes):
    return c.merge(c.DEFAULTS, changes)


def with_reviewers(**edit):
    reviewers = copy.deepcopy(c.DEFAULTS["review"]["reviewers"])
    reviewers[0].update(edit)
    return {"review": {"reviewers": reviewers}}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = str(self.dir / "config.json")

    def write(self, text):
        Path(self.path).write_text(text)


class Defaults(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(c.validate(c.DEFAULTS), [])

    def test_defaults_pin_todays_behaviour(self):
        review, fix = c.DEFAULTS["review"], c.DEFAULTS["fix"]
        self.assertEqual([r["id"] for r in review["reviewers"]], ["opus", "codex", "quality"])
        self.assertEqual((review["workers"], fix["workers"]), (3, 3))
        self.assertEqual((review["rounds"], review["max_added"], review["timeout_s"]), (8, 4000, 2700))
        self.assertEqual(review["trivial"], ["*.lock", "*lock.json", "*.lockb", "*.md", "*.png", "*.jpg", "*.svg"])
        self.assertEqual((fix["turn_timeout_s"], fix["pass_timeout_s"], fix["max_errors"]), (2700, 4 * 3600, 3))
        self.assertEqual((fix["test_retries"], fix["ci_tries"], fix["ci_apps"], fix["gates"]), (2, 3, ["github-actions"], []))
        self.assertEqual(c.DEFAULTS["refresh"], {"interval_s": 300, "idle_s": 60})
        self.assertEqual([r["advisory"] for r in review["reviewers"]], [False, False, True])
        self.assertEqual([r["needs_conventions"] for r in review["reviewers"]], [False, False, True])

    def test_builtin_overrides(self):
        gitops = c.effective(c.DEFAULTS, "iprally/gitops")
        self.assertEqual((gitops["review"]["enabled"], gitops["fix"]["enabled"], gitops["fix"]["gates"]), (False, True, []))
        iprally = c.effective(c.DEFAULTS, "iprally/iprally")
        self.assertEqual([g["name"] for g in iprally["fix"]["gates"]], ["cljfmt", "Karma"])
        self.assertTrue(iprally["review"]["enabled"])
        self.assertEqual(c.effective(c.DEFAULTS, "acme/new")["fix"]["gates"], [])
        self.assertTrue(c.effective(c.DEFAULTS, "acme/new")["review"]["enabled"])

    def test_karma_gate_runs_today_commands(self):
        karma = c.effective(c.DEFAULTS, "iprally/iprally")["fix"]["gates"][1]
        self.assertEqual((karma["cwd"], karma["timeout_s"], karma["slot"]), ("ui", 1800, True))
        self.assertEqual(karma["prelude"], ". ~/.config/nvm/nvm.sh && nvm use 22.15.1 >/dev/null")
        self.assertEqual(karma["setup"]["run"], "(cd .. && npm run postinstall) && npx shadow-cljs compile karma-test")
        self.assertEqual(karma["run"], "npx karma start --single-run --client.args iprally_ui.karma_runner_test.init "
                                       "--client.args {item}")


class Load(Tmp):
    def test_missing_file_gives_defaults_without_error(self):
        got = c.load(self.path)
        self.assertEqual((got.config, got.source, got.error), (c.DEFAULTS, "defaults", None))

    def test_bad_files_give_defaults_and_an_error(self):
        for text in ("{nope", "[]", "null", '{"review": {"workers": 0}}', '{"mystery": 1}', "\xff"):
            with self.subTest(text=text):
                self.write(text)
                got = c.load(self.path)
                self.assertEqual((got.config, got.source), (c.DEFAULTS, "defaults"))
                self.assertTrue(got.error)

    def test_error_names_the_first_problem(self):
        self.write('{"review": {"workers": 0}}')
        self.assertEqual(c.load(self.path).error, "review.workers: must be an integer 1-8")

    def test_unreadable_path_gives_defaults_and_an_error(self):
        got = c.load(str(self.dir))
        self.assertEqual((got.source, bool(got.error)), ("defaults", True))

    def test_partial_file_merges_over_defaults(self):
        self.write('{"review": {"workers": 2}}')
        got = c.load(self.path)
        self.assertEqual((got.source, got.error, got.config["review"]["workers"], got.config["fix"]["workers"]),
                         ("file", None, 2, 3))
        self.assertEqual(got.config["review"]["reviewers"], c.DEFAULTS["review"]["reviewers"])

    def test_env_picks_the_path(self):
        with mock.patch.dict(os.environ, {"PR_WIZARD_CONFIG": self.path}):
            self.assertEqual(c.default_path(), self.path)
            self.write('{"fix": {"workers": 1}}')
            self.assertEqual(c.load().config["fix"]["workers"], 1)

    def test_loaded_config_is_not_the_shared_defaults(self):
        c.load(self.path).config["review"]["workers"] = 8
        self.assertEqual(c.DEFAULTS["review"]["workers"], 3)


class Validate(unittest.TestCase):
    def paths(self, d, level="config"):
        return {p["path"] for p in c.validate(d, level)}

    def test_every_rule(self):
        bad_gate = lambda **kw: {"fix": {"gates": [{"name": "g", "kind": "test", "when": ["*"], "run": "x", **kw}]}}
        cases = {
            "version": {"version": 2},
            "detect.roots": {"detect": {"roots": []}},
            "lanes.separate": {"lanes": {"separate": "yes"}},
            "review.enabled": {"review": {"enabled": 1}},
            "review.workers": {"review": {"workers": 9}},
            "review.rounds": {"review": {"rounds": 51}},
            "review.max_added": {"review": {"max_added": 0}},
            "review.trivial": {"review": {"trivial": []}},
            "review.timeout_s": {"review": {"timeout_s": 59}},
            "review.reviewers": {"review": {"reviewers": []}},
            "review.reviewers[0].id": with_reviewers(id="Bad Id"),
            "review.reviewers[0].label": with_reviewers(label=""),
            "review.reviewers[0].prompt": with_reviewers(prompt="missing.md"),
            "review.reviewers[0].engine": with_reviewers(engine="gpt"),
            "review.reviewers[0].claude.effort": with_reviewers(claude={"model": "opus", "effort": "ultra", "incremental": None}),
            "review.reviewers[0].codex.effort": with_reviewers(codex={"model": None, "effort": "none"}),
            "review.reviewers[0].claude.model": with_reviewers(claude={"model": None, "effort": None, "incremental": None}),
            "review.reviewers[0].claude.incremental.model": with_reviewers(
                claude={"model": "opus", "effort": None, "incremental": {"model": "", "effort": None}}),
            "review.reviewers[0].bogus": with_reviewers(bogus=1),
            "fix.engine": {"fix": {"engine": "claude"}},
            "fix.effort": {"fix": {"effort": "turbo"}},
            "fix.model": {"fix": {"model": ""}},
            "fix.prompt": {"fix": {"prompt": "nope.md"}},
            "fix.turn_timeout_s": {"fix": {"turn_timeout_s": 59}},
            "fix.pass_timeout_s": {"fix": {"pass_timeout_s": 599}},
            "fix.max_errors": {"fix": {"max_errors": 0}},
            "fix.test_retries": {"fix": {"test_retries": 6}},
            "fix.ci_tries": {"fix": {"ci_tries": 11}},
            "fix.ci_apps": {"fix": {"ci_apps": "github-actions"}},
            "fix.gates": {"fix": {"gates": [bad_gate()["fix"]["gates"][0]] * 11}},
            "fix.gates[0].kind": bad_gate(kind="lint"),
            "fix.gates[0].targets.keep": bad_gate(targets={"keep": "("}),
            "fix.gates[0].targets.map[0]": bad_gate(targets={"map": [["(", "x"]]}),
            "fix.gates[0].setup.run": bad_gate(setup={"name": "n"}),
            "fix.gates[0].extra": bad_gate(extra=1),
            "refresh.interval_s": {"refresh": {"interval_s": 59}},
            "refresh.idle_s": {"refresh": {"idle_s": 301}},
            "projects.bad": {"projects": {"bad": {}}},
            "projects.a/b.detect": {"projects": {"a/b": {"detect": {}}}},
            "projects.a/b.root": {"projects": {"a/b": {"root": ""}}},
            "unknown": {"unknown": 1},
        }
        for expected, change in cases.items():
            with self.subTest(expected):
                self.assertIn(expected, self.paths(doc(**change)))

    def test_a_bool_is_not_an_integer(self):
        self.assertIn("review.workers", self.paths(doc(review={"workers": True})))

    def test_a_missing_key_in_a_complete_doc_is_a_problem(self):
        self.assertEqual(self.paths({}), {"version", "detect", "lanes", "projects", "review", "fix", "refresh"})

    def test_too_many_projects_and_roots(self):
        many = {f"o/n{i}": {} for i in range(51)}
        self.assertIn("projects", self.paths(doc(projects=many)))
        self.assertIn("detect.roots", self.paths(doc(detect={"roots": ["~/a"] * 11})))

    def test_duplicate_reviewer_ids(self):
        reviewers = c.DEFAULTS["review"]["reviewers"]
        self.assertIn("review.reviewers[1].id", self.paths(doc(review={"reviewers": [reviewers[0], reviewers[0]]})))

    def test_needs_an_enabled_reviewer_only_when_review_is_on(self):
        off = [{**r, "enabled": False} for r in c.DEFAULTS["review"]["reviewers"]]
        self.assertIn("review.reviewers", self.paths(doc(review={"reviewers": off})))
        self.assertEqual(self.paths(doc(review={"enabled": False, "reviewers": off})), set())

    def test_a_project_can_run_out_of_reviewers(self):
        off = [{**r, "enabled": False} for r in c.DEFAULTS["review"]["reviewers"]]
        self.assertIn("projects.a/b.review.reviewers", self.paths(doc(projects={"a/b": {"review": {"reviewers": off}}})))

    def test_claude_model_is_needed_for_a_claude_run_or_a_fallback(self):
        nothing = {"model": None, "effort": None, "incremental": None}
        self.assertEqual(self.paths(doc(**with_reviewers(engine="codex", fallback=False, claude=nothing))), set())
        self.assertTrue(self.paths(doc(**with_reviewers(engine="codex", fallback=True, claude=nothing))))
        self.assertTrue(self.paths(doc(**with_reviewers(engine="claude", fallback=False, claude=nothing))))

    def test_a_reviewer_needs_only_its_core_fields(self):
        lean = {"id": "lean", "label": "Lean", "prompt": "opus.md", "engine": "claude", "claude": {"model": "opus"}}
        self.assertEqual(self.paths(doc(review={"reviewers": [lean]})), set())
        self.assertIn("review.reviewers[0].label", self.paths(doc(review={"reviewers": [{**lean, "label": None}]})))

    def test_pr_level_rejects_workers_and_root(self):
        for change in ({"review": {"workers": 2}}, {"fix": {"workers": 2}}, {"root": "/x"}, {"lanes": {}}):
            with self.subTest(change):
                self.assertTrue(self.paths(change, "pr"))

    def test_pr_level_accepts_the_allowed_keys(self):
        change = {"review": {"enabled": False, "reviewers": c.DEFAULTS["review"]["reviewers"][:1]},
                  "fix": {"model": "gpt-x", "gates": []}}
        self.assertEqual(self.paths(change, "pr"), set())
        self.assertEqual(self.paths({}, "pr"), set())

    def test_pr_level_checks_the_merged_reviewers(self):
        off = [{**r, "enabled": False} for r in c.DEFAULTS["review"]["reviewers"]]
        self.assertIn("review.reviewers", self.paths({"review": {"reviewers": off}}, "pr"))

    def test_pr_level_merges_over_a_base(self):
        base = {"review": {**c.DEFAULTS["review"], "reviewers": [{**c.DEFAULTS["review"]["reviewers"][0], "enabled": False}]},
                "fix": c.DEFAULTS["fix"]}
        self.assertIn("review.reviewers", {p["path"] for p in c.validate({"fix": {"model": "x"}}, "pr", base)})


class Merge(unittest.TestCase):
    def test_objects_merge_and_arrays_replace(self):
        self.assertEqual(c.merge({"a": {"x": 1, "y": 2}, "l": [1, 2]}, {"a": {"y": 3}, "l": [9]}),
                         {"a": {"x": 1, "y": 3}, "l": [9]})

    def test_null_replaces_in_merge(self):
        self.assertEqual(c.merge({"a": 1, "b": {"c": 2}}, {"a": None, "b": None}), {"a": None, "b": None})

    def test_merge_leaves_inputs_alone(self):
        base, over = {"a": {"l": [1]}}, {"a": {"m": [2]}}
        out = c.merge(base, over)
        out["a"]["l"].append(7)
        out["a"]["m"].append(7)
        self.assertEqual((base, over), ({"a": {"l": [1]}}, {"a": {"m": [2]}}))

    def test_merge_keeps_default_key_order(self):
        self.assertEqual(list(c.merge(c.DEFAULTS, {"refresh": {}, "review": {"workers": 1}})), list(c.DEFAULTS))

    def test_merge_patch_null_deletes(self):
        self.assertEqual(c.merge_patch({"a": 1, "b": {"c": 2, "d": 3}}, {"a": None, "b": {"c": None}}), {"b": {"d": 3}})

    def test_merge_patch_rfc_7396_cases(self):
        target = {"title": "Goodbye!", "author": {"givenName": "John", "familyName": "Doe"}, "tags": ["example", "sample"]}
        patch = {"title": "Hello!", "phoneNumber": "+01-123-456-7890", "author": {"familyName": None}, "tags": ["example"]}
        self.assertEqual(c.merge_patch(target, patch), {"title": "Hello!", "phoneNumber": "+01-123-456-7890",
                                                        "author": {"givenName": "John"}, "tags": ["example"]})
        self.assertEqual(c.merge_patch({"a": "b"}, {"a": {"b": "c"}}), {"a": {"b": "c"}})
        self.assertEqual(c.merge_patch({"e": None}, {"a": 1}), {"e": None, "a": 1})
        self.assertEqual(c.merge_patch(["a", "b"], ["c", "d"]), ["c", "d"])
        self.assertEqual(c.merge_patch({"a": "foo"}, None), None)
        self.assertEqual(c.merge_patch({}, {"a": {"bb": {"ccc": None}}}), {"a": {"bb": {}}})

    def test_patch_drops_a_project_override(self):
        patched = c.merge_patch(c.DEFAULTS, {"projects": {"iprally/gitops": None}})
        self.assertNotIn("iprally/gitops", patched["projects"])
        self.assertEqual(c.validate(patched), [])


class Effective(unittest.TestCase):
    def test_three_levels(self):
        cfg = doc(review={"workers": 2}, projects={"a/b": {"review": {"rounds": 5}, "fix": {"model": "m1"}, "root": "/r"}})
        eff = c.effective(cfg, "a/b", {"review": {"rounds": 6}})
        self.assertEqual((eff["review"]["workers"], eff["review"]["rounds"], eff["fix"]["model"], eff["root"]), (2, 6, "m1", "/r"))
        self.assertEqual(c.effective(cfg, "a/b")["review"]["rounds"], 5)
        self.assertEqual(c.effective(cfg, "x/y")["review"]["rounds"], 8)
        self.assertNotIn("root", c.effective(cfg, "x/y"))

    def test_arrays_replace_across_levels(self):
        one = c.DEFAULTS["review"]["reviewers"][:1]
        cfg = doc(projects={"a/b": {"review": {"trivial": ["*.x"]}}})
        self.assertEqual(c.effective(cfg, "a/b")["review"]["trivial"], ["*.x"])
        eff = c.effective(cfg, "a/b", {"review": {"reviewers": one, "trivial": ["*.y"]}})
        self.assertEqual((eff["review"]["reviewers"], eff["review"]["trivial"]), (one, ["*.y"]))
        self.assertEqual(c.effective(c.DEFAULTS, "iprally/iprally", {"fix": {"gates": []}})["fix"]["gates"], [])

    def test_labels_only_turn_a_lane_off(self):
        self.assertEqual(c.effective(c.DEFAULTS, "a/b", labels=["no-auto-review"])["review"]["enabled"], False)
        self.assertEqual(c.effective(c.DEFAULTS, "a/b", labels=["no-auto-review"])["fix"]["enabled"], True)
        self.assertEqual(c.effective(c.DEFAULTS, "a/b", labels=["no-auto-fix", "x"])["fix"]["enabled"], False)
        pr = {"review": {"enabled": True}}
        self.assertEqual(c.effective(c.DEFAULTS, "iprally/gitops", pr, ["bug"])["review"]["enabled"], True)
        self.assertEqual(c.effective(c.DEFAULTS, "a/b", pr, ["no-auto-review"])["review"]["enabled"], False)

    def test_effective_does_not_touch_the_config(self):
        before = copy.deepcopy(c.DEFAULTS)
        c.effective(c.DEFAULTS, "a/b", {"review": {"workers": 1}}, ["no-auto-review", "no-auto-fix"])
        self.assertEqual(c.DEFAULTS, before)


class Rev(unittest.TestCase):
    def test_rev_is_12_hex_and_stable(self):
        self.assertRegex(c.rev(c.DEFAULTS), r"^[0-9a-f]{12}$")
        self.assertEqual(c.rev(c.DEFAULTS), c.rev(copy.deepcopy(c.DEFAULTS)))
        self.assertEqual(c.rev({"a": 1, "b": 2}), c.rev({"b": 2, "a": 1}))

    def test_rev_moves_with_the_content(self):
        self.assertNotEqual(c.rev(c.DEFAULTS), c.rev(doc(fix={"workers": 1})))
        self.assertEqual(c.rev({}), c.rev({}))

    def test_load_reports_the_rev_of_its_config(self):
        self.assertEqual(c.load("/nonexistent/x").rev, c.rev(c.DEFAULTS))


class Save(Tmp):
    def test_round_trip(self):
        cfg = doc(review={"workers": 2})
        c.save(cfg, self.path)
        got = c.load(self.path)
        self.assertEqual((got.source, got.config, got.rev), ("file", cfg, c.rev(cfg)))

    def test_format_is_indented_json_with_a_newline_in_default_order(self):
        cfg = doc(review={"workers": 2})
        c.save(cfg, self.path)
        text = Path(self.path).read_text()
        self.assertEqual(text, json.dumps(cfg, indent=2) + "\n")
        self.assertEqual(list(json.loads(text)), list(c.DEFAULTS))

    def test_symlink_survives_and_the_real_file_changes(self):
        real_dir = self.dir / "chezmoi" / ".pr-wizard"
        real_dir.mkdir(parents=True)
        real = real_dir / "config.json"
        real.write_text("{}")
        link = self.dir / "config-link.json"
        link.symlink_to(real)
        c.save(doc(fix={"workers": 1}), str(link))
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(real))
        self.assertEqual(json.loads(real.read_text())["fix"]["workers"], 1)
        self.assertEqual(c.load(str(link)).real_path, str(real.resolve()))

    def test_a_dangling_symlink_loads_the_defaults_and_save_creates_the_real_file(self):
        real = self.dir / "chezmoi" / ".pr-wizard" / "config.json"
        link = self.dir / "config-link.json"
        link.symlink_to(real)
        got = c.load(str(link))
        self.assertEqual((got.config, got.source, got.error), (c.DEFAULTS, "defaults", None))
        c.save(doc(fix={"workers": 1}), str(link))
        self.assertTrue(link.is_symlink() and real.is_file())
        self.assertEqual(c.load(str(link)).source, "file")

    def test_temp_file_sits_beside_the_resolved_real_path(self):
        real_dir = self.dir / "src"
        real_dir.mkdir()
        real = real_dir / "config.json"
        link = self.dir / "link.json"
        link.symlink_to(real)
        with mock.patch("os.replace", wraps=os.replace) as replace:
            c.save(c.DEFAULTS, str(link))
        tmp, dest = replace.call_args.args
        self.assertEqual((os.path.dirname(tmp), dest), (str(real_dir.resolve()), str(real.resolve())))
        self.assertEqual(os.listdir(real_dir), ["config.json"])

    def test_mode_is_copied_and_new_files_are_0644(self):
        c.save(c.DEFAULTS, self.path)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        os.chmod(self.path, 0o600)
        c.save(doc(fix={"workers": 2}), self.path)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_creates_a_missing_directory(self):
        path = str(self.dir / "new" / "dir" / "config.json")
        c.save(c.DEFAULTS, path)
        self.assertEqual(c.load(path).source, "file")

    def test_a_failed_write_leaves_no_temp_and_keeps_the_file(self):
        c.save(c.DEFAULTS, self.path)
        before = Path(self.path).read_text()
        with mock.patch("os.replace", side_effect=OSError("boom")), self.assertRaises(OSError):
            c.save(doc(fix={"workers": 2}), self.path)
        self.assertEqual((Path(self.path).read_text(), os.listdir(self.dir)), (before, ["config.json"]))


class Choices(Tmp):
    def test_static_lists_and_prompts(self):
        got = c.choices(str(self.dir))
        self.assertEqual(got["engines"], ["claude", "codex"])
        self.assertEqual(got["fix_engines"], ["codex"])
        self.assertEqual(got["gate_kinds"], ["format", "test"])
        self.assertEqual(got["claude_efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(got["codex_efforts"][-1], "ultra")
        self.assertEqual(got["prompts"], sorted(p.name for p in (ROOT / "review/prompts").glob("*.md")))

    def test_unreadable_codex_home_gives_empty_suggestions(self):
        got = c.choices(str(self.dir / "none"))
        self.assertEqual((got["codex_models"], got["codex_default"]), ([], None))

    def test_codex_models_and_default_are_read(self):
        (self.dir / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": "m1", "default_reasoning_level": "medium", "visibility": "list",
             "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]},
            {"slug": "hidden", "visibility": "hide", "supported_reasoning_levels": []}]}))
        (self.dir / "config.toml").write_text('model = "m1"\nmodel_reasoning_effort = "high"\n[projects]\nmodel = "x"\n')
        got = c.choices(str(self.dir))
        self.assertEqual(got["codex_models"], [{"model": "m1", "efforts": ["low", "high"], "default_effort": "medium"}])
        self.assertEqual(got["codex_default"], {"model": "m1", "effort": "high"})

    def test_a_model_line_without_effort(self):
        (self.dir / "config.toml").write_text('model = "m1"\n')
        self.assertEqual(c.choices(str(self.dir))["codex_default"], {"model": "m1", "effort": None})

    def test_a_garbled_cache_gives_no_models(self):
        (self.dir / "models_cache.json").write_text('{"models": [{"nope": 1}]}')
        self.assertEqual(c.choices(str(self.dir))["codex_models"], [])


if __name__ == "__main__":
    unittest.main()
