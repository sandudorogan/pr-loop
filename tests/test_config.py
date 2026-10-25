import copy
import unittest

from pr_wizard import config as c

def doc(**changes):
    return c.merge(c.DEFAULTS, changes)


def with_reviewers(**edit):
    reviewers = copy.deepcopy(c.DEFAULTS["review"]["reviewers"])
    reviewers[0].update(edit)
    return {"review": {"reviewers": reviewers}}


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


if __name__ == "__main__":
    unittest.main()
