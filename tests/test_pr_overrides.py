"""The third override level (api.md §3.14–3.16, §4.10): defaults ⊕ project ⊕ PR ⊗ labels."""
import contextlib
import io
import json
import os
import tempfile
from unittest.mock import patch

from prs import GITOPS, HEAD, MONOREPO, pr, rq
from test_api_write import Writes
from test_engine_args import scripts
from test_events import Store
from test_history import Asked, node
from pr_wizard import config, db, history

OPUS = [config.DEFAULTS["review"]["reviewers"][0]]
SCOPE = {"head": HEAD, "done_at_head": ["solo", "codex"], "clean_at_head": []}


class Levels(Store):
    def test_each_level_overrides_the_one_above_and_labels_only_turn_a_lane_off(self):
        self.assertFalse(config.effective_for(GITOPS, 7, cfg=config.DEFAULTS)["review"]["enabled"])
        db.put_pr_override(GITOPS, 7, {"review": {"enabled": True, "reviewers": OPUS}})
        eff = config.effective_for(GITOPS, 7, cfg=config.DEFAULTS)
        self.assertEqual((eff["review"]["enabled"], eff["review"]["reviewers"]), (True, OPUS))
        self.assertFalse(config.effective_for(GITOPS, 7, ["no-auto-review"], config.DEFAULTS)["review"]["enabled"])
        self.assertEqual(config.effective_for(GITOPS, 8, cfg=config.DEFAULTS), config.effective(config.DEFAULTS, GITOPS))

    def test_the_queue_gates_lanes_and_reviewers_follow_the_pr(self):
        db.put_pr_override(MONOREPO, 5, {"review": {"enabled": False, "reviewers": OPUS}, "fix": {"enabled": False}})
        self.assertTrue(rq.unreviewed(pr(5)) and rq.unfixed(pr(5)))
        self.assertFalse(rq.unreviewed(pr(6)) or rq.unfixed(pr(6)))
        self.assertEqual((rq.reviewers(MONOREPO, 5), rq.reviewers(MONOREPO, 6)), (["opus"], ["opus", "codex", "quality"]))
        self.assertEqual(rq.row(pr(5), {}, {}, []), (4, "skipped", "lanes off"))

    def test_the_gates_read_the_pr_rounds_and_size(self):
        db.put_pr_override(MONOREPO, 5, {"review": {"max_added": 10}})
        self.assertEqual(rq.decide(pr(5, additions=11, requested=True), {"sha": "x", "files": {}}, {"a": "1"}, None)[0],
                         "too-big")
        self.assertIsNone(rq.decide(pr(6, additions=11, requested=True), {"sha": "x", "files": {}}, {"a": "1"}, None))


class Api(Writes):
    def url(self, n=10, repo=MONOREPO):
        return f"/v1/prs/{repo}/{n}/config"

    def patch_(self, body, n=10, repo=MONOREPO):
        return self.call("PATCH", self.url(n, repo), body)

    def test_get_without_an_override_shows_the_project_layer(self):
        status, body = self.call("GET", self.url())
        self.assertEqual((status, body["override"], body["rev"], body["created_at"]), (200, None, config.rev({}), None))
        self.assertEqual(body["layers"], {"project": ["fix.gates"], "pr": []})
        self.assertEqual(body["effective"], config.effective(config.DEFAULTS, MONOREPO))

    def test_patch_stores_the_override_and_the_item_badge_follows(self):
        status, body = self.patch_({"base_rev": config.rev({}), "patch": {"review": {"reviewers": OPUS}}})
        self.assertEqual((status, body["layers"]["pr"], body["effective"]["review"]["reviewers"]), (200, ["review.reviewers"], OPUS))
        self.assertEqual(db.pr_override(MONOREPO, 10)["config"], {"review": {"reviewers": OPUS}})
        self.assertEqual(self.call("GET", self.url())[1], body)
        items = {i["number"]: i for i in self.call("GET", "/v1/queue")[1]["items"]}
        self.assertEqual((items[10]["override"], items[13]["override"]), (["review.reviewers"], []))
        self.assertTrue(self.refetched())

    def test_a_null_deletes_a_key_and_an_empty_override_is_none(self):
        self.patch_({"patch": {"review": {"enabled": False}, "fix": {"enabled": False}}})
        self.assertEqual(self.patch_({"patch": {"fix": None}})[1]["override"], {"review": {"enabled": False}})
        self.assertIsNone(self.patch_({"patch": {"review": None}})[1]["override"])
        self.assertIsNone(db.pr_override(MONOREPO, 10))

    def test_put_keeps_a_null_over_the_project_model(self):
        self.call("PATCH", "/v1/config", {"patch": {"projects": {MONOREPO: {"fix": {"model": "gpt-5"}}}}})
        self.assertEqual(self.patch_({"patch": {"fix": {"model": None}}})[1]["effective"]["fix"]["model"], "gpt-5")
        status, body = self.call("PUT", self.url(), {"override": {"fix": {"model": None}}})
        self.assertEqual((status, body["layers"]["pr"], body["effective"]["fix"]["model"]), (200, ["fix.model"], None))
        self.assertEqual(db.pr_override(MONOREPO, 10)["config"], {"fix": {"model": None}})

    def test_put_replaces_the_whole_override(self):
        self.patch_({"patch": {"review": {"enabled": False}}})
        body = self.call("PUT", self.url(), {"override": {"fix": {"enabled": False}}})[1]
        self.assertEqual(body["override"], {"fix": {"enabled": False}})
        self.assertIsNone(self.call("PUT", self.url(), {"override": {}})[1]["override"])
        status, body = self.call("PUT", self.url(), {"base_rev": "0" * 12, "override": {}})
        self.assertEqual((status, body["error"]["code"]), (412, "stale_config"))

    def test_labels_force_their_lane_off(self):
        body = self.patch_({"patch": {"fix": {"enabled": True}}}, 17)[1]
        self.assertEqual((body["labels"], body["effective"]["fix"]["enabled"]), (["no-auto-fix"], False))

    def test_workers_and_root_are_422(self):
        for patch_, where in (({"review": {"workers": 2}}, "review.workers"), ({"fix": {"workers": 2}}, "fix.workers"),
                              ({"root": "/x"}, "root")):
            status, body = self.patch_({"patch": patch_})
            self.assertEqual((status, body["error"]["code"], [d["path"] for d in body["error"]["details"]]),
                             (422, "invalid_config", [where]))
        self.assertEqual(self.patch_({"patch": {"review": {"reviewers": [dict(OPUS[0], enabled=False)]}}})[0], 422)
        self.assertIsNone(db.pr_override(MONOREPO, 10))

    def test_a_stale_base_rev_is_412(self):
        self.patch_({"patch": {"review": {"enabled": False}}})
        status, body = self.patch_({"base_rev": config.rev({}), "patch": {"fix": {"enabled": False}}})
        self.assertEqual((status, body["error"]["code"]), (412, "stale_config"))
        self.assertEqual(db.pr_override(MONOREPO, 10)["config"], {"review": {"enabled": False}})

    def test_delete_drops_the_override(self):
        self.patch_({"patch": {"review": {"enabled": False}}})
        status, body = self.call("DELETE", self.url())
        self.assertEqual((status, body["override"], body["layers"]["pr"]), (200, None, []))
        self.assertIsNone(db.pr_override(MONOREPO, 10))

    def test_unknown_prs_are_404(self):
        for path, code in ((self.url(1, "acme/nope"), "unknown_repo"), (self.url(11), "not_in_queue")):
            for method, body in (("GET", None), ("PUT", {"override": {}}), ("PATCH", {"patch": {}}), ("DELETE", None)):
                status, body = self.call(method, path, body)
                self.assertEqual((status, body["error"]["code"]), (404, code), (method, path))

    def test_review_now_follows_the_pr_review_lane(self):
        self.patch_({"patch": {"review": {"enabled": False}}})
        with patch.object(rq, "review_now") as review_now:
            self.assertEqual(self.call("POST", f"/v1/prs/{MONOREPO}/10/review")[1]["error"]["code"], "review_lane_off")
            self.patch_({"patch": {"review": {"enabled": True}}}, 20, GITOPS)
            self.assertEqual(self.call("POST", f"/v1/prs/{GITOPS}/20/review")[0], 202)
        review_now.assert_called_once_with(GITOPS, 20)


class Lifetime(Store):
    def setUp(self):
        super().setUp()
        history.LOOKED.clear()

    def settle(self, nodes, prs=()):
        history.settle(Asked(nodes), list(prs), lambda _: None)

    def test_merge_or_close_drops_it_and_a_new_head_keeps_it(self):
        for n in (1, 2, 3, 4):
            db.put_pr_override(MONOREPO, n, {"review": {"enabled": False}})
        db.upsert_history(MONOREPO, 1, title="x")
        self.settle({(MONOREPO, 1): node("MERGED"), (MONOREPO, 2): node("CLOSED"), (MONOREPO, 3): node("OPEN")},
                    [pr(4, head="f" * 40)])
        self.assertEqual(list(db.pr_overrides()), [(MONOREPO, 3), (MONOREPO, 4)])
        self.assertEqual([(h["number"], h["state"]) for h in db.history()], [(1, "merged")])


class ByHand(Store):
    """A script run by hand reads the PR's override itself, so it runs what a daemon run would."""

    def setUp(self):
        super().setUp()
        self.scripts = scripts()
        self.prr, self.fix = self.scripts.__enter__()
        self.addCleanup(self.scripts.__exit__, None, None, None)

    def review_main(self, *argv):
        with patch("sys.argv", ["pr_review.py", *argv]), patch.object(self.prr.names, "migrate"), \
                patch.object(self.prr, "scope", return_value=SCOPE), contextlib.redirect_stdout(io.StringIO()):
            self.prr.main()

    def fix_dump(self, n):
        with patch("sys.argv", ["pr_fix.py", "dump", "--pr", str(n)]), patch.object(self.fix.names, "migrate"), \
                patch.object(self.fix, "sh", return_value=json.dumps({"headRefOid": HEAD})), \
                patch.object(self.fix, "feedback", return_value=[]), patch.object(self.fix, "checks", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.fix.main()

    def test_pr_review_takes_the_pr_reviewers_and_timeout(self):
        db.put_pr_override(MONOREPO, 5, {"review": {"timeout_s": 123, "reviewers": [dict(OPUS[0], id="solo")]}})
        self.review_main("run", "--pr", "6", "--reviewer", "codex")
        self.assertEqual((self.prr.TIMEOUT, sorted(self.prr.REVIEWERS)), (2700, ["codex", "opus", "quality"]))
        self.review_main("run", "--pr", "5", "--reviewer", "solo", "--dry-run")
        self.assertEqual((self.prr.TIMEOUT, sorted(self.prr.REVIEWERS)), (123, ["solo"]))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.review_main("run", "--pr", "5", "--reviewer", "opus")

    def test_pr_fix_takes_the_pr_fixer(self):
        db.put_pr_override(MONOREPO, 5, {"fix": {"turn_timeout_s": 99, "prompt": "merge.md", "gates": []}})
        self.fix_dump(5)
        self.assertEqual((self.fix.TIMEOUT, self.fix.GATES, os.path.basename(self.fix.PROMPT)), (99, [], "merge.md"))
        self.fix_dump(6)
        self.assertEqual((self.fix.TIMEOUT, [g["name"] for g in self.fix.GATES]), (2700, ["cljfmt", "Karma"]))
