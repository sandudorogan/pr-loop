import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from prs import GITOPS, HEAD, MONOREPO, pr, rq
from test_events import Store
import test_api_read
from test_api_read import fixture, shape
from pr_loop import db, history

OTHER = "b" * 40


def ago(days=0, hours=0):
    return (datetime.now().astimezone() - timedelta(days=days, hours=hours)).isoformat(timespec="seconds")


def node(state="OPEN", mine=True, title="t", closed=None):
    return {"state": state, "title": title, "url": "u", "closedAt": closed, "viewerDidAuthor": mine,
            "headRefOid": HEAD, "author": {"login": "colleague"}}


class Asked:
    """A fake `graphql`: answers every `pullRequest(number: N)` alias of a query from `nodes`, and counts the calls."""

    def __init__(self, nodes):
        self.nodes, self.queries = nodes, []

    def __call__(self, query, variables):
        self.queries.append(query)
        data = {"rateLimit": {"cost": 1}}
        for part in re.split(r"(?=r\d+: repository)", query)[1:]:
            alias, owner, name = re.match(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', part).groups()
            data[alias] = {f"p{n}": self.nodes[f"{owner}/{name}", int(n)] for n in re.findall(r"p(\d+): pullRequest", part)}
        return data


class Remember(Store):
    def setUp(self):
        super().setUp()
        history.LOOKED.clear()

    def handle(self, p, outcome, seen=None, skip=None):
        with patch.object(rq, "load", return_value={str(p["number"]): seen or {}}), \
                patch.object(rq, "fingerprint", return_value={"a.py": "2"}), patch.object(rq, "decide", return_value=skip), \
                patch.object(rq, "review", return_value=outcome), patch.object(rq, "post_clean_notice"), \
                patch.object(rq, "in_review"), \
                patch.object(rq, "kick"), patch.object(rq, "save_bumped"), patch.object(rq, "bumped", return_value=[]), \
                patch.object(rq, "log_once"), patch.object(rq, "log"):
            rq.handle(p, [], True, False)

    def fix(self, p, status):
        out = rq.subprocess.CompletedProcess([], 0, '{"status": "%s", "pushed": "%s", "fixed": 1, "refuted": 0, "deferred": 0}'
                                             % (status, HEAD), "")
        with patch.object(rq.subprocess, "run", return_value=out), patch.object(rq, "log"), \
                patch.object(rq, "in_review"), patch.object(rq, "kick"), patch.object(rq, "fix_note", return_value="n"):
            rq.fix(p, [])

    def outcome(self, n=1):
        return next(h for h in db.history() if h["number"] == n)["outcome"]

    def test_every_review_result_upserts_in_its_transaction(self):
        for n, mine, result, want in ((1, False, ("clean", "no findings"), "ready"), (2, True, ("clean", "no findings"), "clean"),
                                      (3, True, ("posted", "opus"), "posted"), (4, False, ("posted", "quality"), "ready"),
                                      (5, True, ("failed", "opus failed 3×"), "failed")):
            self.handle(pr(n, mine=mine, requested=not mine), result)
            self.assertEqual(self.outcome(n), want, n)
        self.assertEqual({h["state"] for h in db.history()}, {"open"})

    def test_a_gate_that_sends_it_to_a_human_counts_but_a_quiet_skip_does_not(self):
        self.handle(pr(1), None, skip=("too-big", "9 added lines"))
        self.handle(pr(2), None, skip=("needs-human", "3 rounds"))
        for n, status in ((3, "unchanged"), (4, "trivial"), (5, "held"), (6, "baseline"), (7, "limited")):
            self.handle(pr(n), None, skip=(status, "x"))
        self.assertEqual([(h["number"], h["outcome"]) for h in db.history()], [(2, "needs-human"), (1, "too-big")])

    def test_the_row_carries_the_pr_and_the_highest_round(self):
        for reviewer, round_ in (("opus", 2), ("codex", 3)):
            db.put_reviewer_result(MONOREPO, 1, HEAD, reviewer, {"result": "posted", "round": round_})
        self.handle(pr(1, mine=False, requested=True), ("posted", "opus"))
        (h,) = db.history()
        self.assertEqual((h["title"], h["author"], h["mine"], h["head"], h["rounds"], h["url"]),
                         ("title 1", "colleague", False, HEAD, 3, f"https://github.com/{MONOREPO}/pull/1"))

    def test_fix_results_set_the_outcome_and_count_pushes(self):
        self.handle(pr(1), ("posted", "opus"))
        self.fix(pr(1), "pushed")
        self.fix(pr(1), "pushed")
        self.assertEqual((self.outcome(), db.history()[0]["fixes_pushed"]), ("pushed", 2))
        self.fix(pr(1), "nothing-to-fix")
        self.assertEqual((self.outcome(), db.history()[0]["fixes_pushed"]), ("nothing-to-fix", 2))

    def test_a_limited_fix_pass_leaves_the_row_alone(self):
        self.handle(pr(1), ("posted", "opus"))
        self.fix(pr(1), "limited")
        self.assertEqual(self.outcome(), "posted")

    def test_a_new_result_reopens_a_closed_entry(self):
        self.handle(pr(1), ("posted", "opus"))
        db.upsert_history(MONOREPO, 1, state="closed", closed_at=db.now())
        self.handle(pr(1), ("clean", "no findings"))
        (h,) = db.history()
        self.assertEqual((h["state"], h["closed_at"]), ("open", None))

    def test_retention_trims_in_the_result_transaction(self):
        with patch.object(db, "HISTORY_KEEP", 2):
            for n in (1, 2, 3):
                self.handle(pr(n), ("posted", "opus"))
        self.assertEqual([h["number"] for h in db.history()], [3, 2])
        db.upsert_history(MONOREPO, 9, title="old", at=ago(days=31))
        self.assertNotIn(9, [h["number"] for h in db.history()])


class Settle(Store):
    def setUp(self):
        super().setUp()
        history.LOOKED.clear()
        self.said = []

    def settle(self, asked, prs=()):
        history.settle(asked, list(prs), self.said.append)

    def test_a_pr_that_left_the_fetch_takes_the_state_github_gives(self):
        for n in (1, 2, 3):
            db.upsert_history(MONOREPO, n, title=str(n), at=ago(hours=n))
        asked = Asked({(MONOREPO, 1): node("MERGED"), (MONOREPO, 2): node("CLOSED"), (MONOREPO, 3): node("OPEN")})
        self.settle(asked)
        got = {h["number"]: (h["state"], h["closed_at"] is not None) for h in db.history()}
        self.assertEqual(got, {1: ("merged", True), 2: ("closed", True), 3: ("open", False)})
        self.assertEqual(len(asked.queries), 1)
        self.assertIn("lookup cost 1 points", self.said[0])

    def test_a_merge_drops_the_done_mark(self):
        db.mark_done(MONOREPO, 1, True)
        self.settle(Asked({(MONOREPO, 1): node("MERGED")}))
        self.assertEqual(db.done_prs(), {})

    def test_the_merge_keeps_the_time_of_the_last_pass(self):
        at = ago(hours=5)
        db.upsert_history(MONOREPO, 1, title="x", at=at)
        self.settle(Asked({(MONOREPO, 1): node("MERGED")}))
        self.assertEqual(db.history()[0]["at"], at)

    def test_a_pr_still_in_the_fetch_costs_nothing(self):
        db.upsert_history(MONOREPO, 1, title="x")
        asked = Asked({})
        self.settle(asked, [pr(1)])
        self.assertEqual(asked.queries, [])

    def test_an_open_pr_is_asked_again_only_after_the_recheck(self):
        db.upsert_history(MONOREPO, 1, title="x")
        asked = Asked({(MONOREPO, 1): node("OPEN")})
        self.settle(asked)
        self.settle(asked)
        self.assertEqual(len(asked.queries), 1)
        history.LOOKED[MONOREPO, 1] -= history.RECHECK
        self.settle(asked)
        self.assertEqual(len(asked.queries), 2)

    def test_a_closed_entry_is_never_asked_again(self):
        db.upsert_history(MONOREPO, 1, title="x", state="merged", closed_at=db.now())
        asked = Asked({})
        self.settle(asked)
        self.assertEqual(asked.queries, [])

    def test_the_lookup_batches_twenty_prs_across_repos(self):
        nodes = {}
        for n in range(1, 26):
            repo = GITOPS if n % 5 == 0 else MONOREPO
            db.upsert_history(repo, n, title=str(n), at=ago(hours=n))
            nodes[repo, n] = node("MERGED")
        asked = Asked(nodes)
        self.settle(asked)
        self.assertEqual(len(asked.queries), 2)
        self.assertEqual({h["state"] for h in db.history()}, {"merged"})
        self.assertTrue(all("search(" not in q for q in asked.queries))


class Seed(Store):
    def setUp(self):
        super().setUp()
        self.said = []

    def put(self, n, review=None, fix=None, repo=MONOREPO, days=1):
        at = (datetime.now() - timedelta(days=days)).strftime("%F %T")
        if review:
            db.put_review(repo, n, {"sha": HEAD, "status": review[0], "verdict": review[1], "rounds": 2, "at": at})
        if fix:
            db.put_fix(repo, n, {"sha": OTHER, "status": fix, "at": at})

    def test_seeds_once_from_the_stored_results(self):
        self.put(1, ("clean", "clean"))
        self.put(2, ("posted", "posted"), fix="pushed", days=2)
        self.put(3, fix="tests-red", repo=GITOPS)
        self.put(4, ("baseline", None))
        self.put(5, ("posted", "posted"), days=40)
        asked = Asked({(MONOREPO, 2): node("MERGED", closed=ago(days=1)), (GITOPS, 3): node("OPEN")})
        history.seed(asked, [pr(1, mine=False)], self.said.append)
        got = {h["number"]: h for h in db.history()}
        self.assertEqual(sorted(got), [1, 2, 3])
        self.assertEqual((got[1]["outcome"], got[1]["state"], got[1]["mine"], got[1]["rounds"]), ("ready", "open", False, 2))
        self.assertEqual((got[2]["outcome"], got[2]["state"], got[2]["fixes_pushed"], got[2]["head"]),
                         ("pushed", "merged", 1, OTHER))
        self.assertIsNotNone(got[2]["closed_at"])
        self.assertEqual((got[3]["outcome"], got[3]["author"]), ("tests-red", "colleague"))
        self.assertEqual(len(asked.queries), 1)
        history.seed(asked, [], self.said.append)
        self.assertEqual(len(asked.queries), 1)
        self.assertIn("seeded 3 PR(s)", self.said[0])

    def test_a_pr_with_a_row_is_kept_as_it_is(self):
        self.put(1, ("clean", "clean"))
        db.upsert_history(MONOREPO, 1, title="kept", outcome="approved")
        history.seed(Asked({}), [], self.said.append)
        self.assertEqual([(h["title"], h["outcome"]) for h in db.history()], [("kept", "approved")])


class Api(unittest.TestCase):
    setUp = test_api_read.Server.setUp
    get = test_api_read.Server.get

    def row(self, n, repo=MONOREPO, **fields):
        db.upsert_history(repo, n, **{"title": f"t{n}", "url": f"u{n}", "author": "colleague",
                                      "author_name": "Aino Virtanen", "mine": False, "outcome": "ready", "head": HEAD, "at": ago(hours=n)} | fields)

    def entries(self, query=""):
        status, _, body = self.get(f"/v1/history{query}")
        self.assertEqual(status, 200)
        return body["entries"]

    def test_the_queue_keeps_what_it_still_works(self):
        groups = {i["key"]: i["group"] for i in self.rt.snapshot()["items"]}
        self.assertEqual((groups[f"{MONOREPO}#10"], groups[f"{MONOREPO}#12"], groups[f"{MONOREPO}#22"]),
                         ("active", "queued", "ready"))
        for n in (10, 12, 22):
            self.row(n)
        self.row(99, state="merged", closed_at=ago())
        self.assertEqual([(e["number"], e["state"], e["done"]) for e in self.entries()],
                         [(22, "settled", False), (99, "merged", True)])

    def test_a_standing_approval_is_the_outcome(self):
        self.row(17, outcome="clean")
        self.assertEqual([(e["number"], e["outcome"], e["done"]) for e in self.entries()], [(17, "approved", True)])

    def test_newest_first_with_a_limit_and_a_repo(self):
        for n in (30, 31, 32):
            self.row(n)
        self.row(5, GITOPS, at=ago(days=2))
        self.assertEqual([e["number"] for e in self.entries()], [30, 31, 32, 5])
        self.assertEqual([e["number"] for e in self.entries("?limit=2")], [30, 31])
        self.assertEqual([e["number"] for e in self.entries(f"?repo={GITOPS}")], [5])
        self.assertEqual(self.entries("?repo=acme/nope"), [])

    def test_the_limit_counts_only_what_shows(self):
        self.row(10, at=ago(hours=0))
        self.row(30)
        self.assertEqual([e["number"] for e in self.entries("?limit=1")], [30])

    def test_a_bad_limit_is_a_400(self):
        for limit in ("0", "501", "x"):
            self.assertEqual(self.get(f"/v1/history?limit={limit}")[0], 400, limit)
        self.assertEqual(self.get("/v1/history", "POST")[0], 405)

    def test_entries_have_the_fixture_shape(self):
        like = fixture("history")["entries"][0]
        self.row(22, repo=MONOREPO, rounds=2, fixes_pushed=1, first_at=ago(days=1))
        self.row(99, state="merged", closed_at=ago(), first_at=ago(days=1))
        settled, merged = self.entries()
        self.assertEqual(shape(settled, like, ("findings", "closed_at")), [])
        self.assertEqual(shape(merged, like, ("findings",)), [])
        self.assertEqual((settled["closed_at"], settled["key"], settled["state"]), (None, f"{MONOREPO}#22", "settled"))

    def test_findings_are_the_snapshot_digest_of_the_last_head(self):
        self.row(13)
        (entry,) = self.entries()
        item = next(i for i in self.rt.snapshot()["items"] if i["number"] == 13)
        self.assertEqual(entry["findings"], item["findings"])
        self.assertIsNotNone(entry["findings"])
        self.row(22)
        self.assertIsNone(next(e for e in self.entries() if e["number"] == 22)["findings"])

    def test_findings_have_the_fixture_shape(self):
        like = fixture("history")["entries"][0]["findings"]
        self.row(13)
        found = self.entries()[0]["findings"]
        self.assertEqual(found.keys(), like.keys())
        self.assertEqual(found["reviewers"][0].keys(), like["reviewers"][0].keys())


if __name__ == "__main__":
    unittest.main()
