import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from prs import GITOPS, MONOREPO, pr, rq
from pr_wizard import config, db, names, snapshot

FIXTURES = Path(__file__).parent / "fixtures"
OLD, HEAD = "0" * 40, "a" * 40
SINCE = "2026-10-25T12:01:02+00:00"
RUNTIME = {"generated_at": "2026-10-25T12:03:10+00:00", "fetched_at": "2026-10-25T12:00:41+00:00", "paused": False,
           "refresh": {"last_at": "2026-10-25T12:00:41+00:00", "last_error": None}}
NULLABLE = {"items[].active.reviewers", "items[].review.verdict"}


def digest(*severities):
    counts = {s: severities.count(s) for s in ("critical", "high", "medium", "low")}
    top = [{"severity": s, "title": f"{s} {i}", "file": "a.py", "line": i} for i, s in enumerate(severities[:3])]
    return {"counts": counts, "at_floor": len([s for s in severities if s != "low"]), "top": top}


def item(n, repo=MONOREPO, author="me", **kw):
    return dict(pr(n, repo, **kw), author={"login": author} if author else None, updatedAt="2026-10-25T11:00:00Z")


def review(sha=HEAD, status="posted", verdict="posted", note="opus", hold=False, at="2026-10-25 10:00:00"):
    return {"sha": sha, "status": status, "verdict": verdict, "note": note, "rounds": 1, "hold": hold, "at": at,
            "files": {"a.py": "x"}}


def fix(status, sha=HEAD, errors=0):
    return {"sha": sha, "key": "k", "status": status, "note": status, "errors": errors, "at": "2026-10-25 10:30:00"}


def script():
    """Every -l group across both repos. Returns the fetched PRs."""
    db.put_review(MONOREPO, 10, review(OLD, note="opus, codex"))
    db.put_fix(MONOREPO, 10, fix("pushed", OLD))
    for reviewer, row in (("opus", digest("high", "medium")), ("codex", digest("medium", "medium", "low"))):
        db.put_reviewer_result(MONOREPO, 10, OLD, reviewer, {"result": "posted", "engine": "claude", "round": 1,
                                                             "digest": row, "url": f"u/{reviewer}"})
    db.put_reviewer_result(MONOREPO, 10, OLD, "quality", {"result": "clean", "engine": "claude", "round": 1,
                                                          "digest": digest()})
    db.run_start(MONOREPO, 10, "review", since=SINCE, reviewers=[
        {"id": "opus", "state": "running", "attempt": 1, "since": SINCE},
        {"id": "codex", "state": "waiting", "attempt": 2, "since": SINCE}])
    db.bump(MONOREPO, 12)
    db.put_review(MONOREPO, 13, review(verdict="quality-only", note="quality"))
    db.put_reviewer_result(MONOREPO, 13, HEAD, "quality", {"result": "posted", "engine": "claude", "round": 2,
                                                           "digest": digest("medium", "low"), "url": "u/q"})
    db.put_review(MONOREPO, 14, review())
    db.put_fix(MONOREPO, 14, fix("refuted-only"))
    db.put_review(MONOREPO, 15, review())
    db.put_fix(MONOREPO, 15, fix("tests-red", OLD, errors=3))
    db.put_review(MONOREPO, 16, review(status="failed", verdict=None, note="opus failed 3×"))
    db.put_reviewer_result(MONOREPO, 16, HEAD, "codex", {"result": "clean", "engine": "codex", "round": 1,
                                                         "digest": digest()})
    db.put_review(MONOREPO, 19, review(OLD, status="clean", verdict="clean", hold=True))
    db.put_review(MONOREPO, 22, review(status="clean", verdict="clean", note="no findings"))
    db.put_fix(GITOPS, 10, fix("nothing-to-fix"))
    db.run_start(GITOPS, 21, "fix", since="2026-10-25T12:05:00+00:00")
    return [item(10), item(11, author="colleague", mine=False, requested=True),
            item(12, author="colleague", mine=False), item(13, author=None, mine=False, requested=True),
            item(14), item(15), item(16, mine=False, requested=True),
            item(17, mine=False, approvals=[True]), item(18, mine=False), item(19), item(20, labels=[rq.NO_REVIEW]),
            item(22, mine=False), item(10, GITOPS), item(21, GITOPS)]


def spec(values, path=""):
    """What the fixture allows at one path: JSON kinds, the keys of objects, the spec of list elements."""
    kinds = {kind(v) for v in values} | ({"null"} if path in NULLABLE else set())
    dicts, lists = [v for v in values if isinstance(v, dict)], [v for v in values if isinstance(v, list)]
    keys = {k for d in dicts for k in d}
    return {"kinds": kinds, "date": any(v is not None for v in values) and all(dated(v) for v in values if v is not None),
            "keys": {k: spec([d[k] for d in dicts if k in d], f"{path}.{k}".lstrip(".")) for k in keys},
            "items": spec([x for l in lists for x in l], f"{path}[]") if any(lists) else None}


def kind(v):
    return "null" if v is None else "bool" if isinstance(v, bool) else type(v).__name__


def dated(v):
    try:
        return datetime.fromisoformat(v).tzinfo is not None
    except (TypeError, ValueError):
        return False


def mismatches(value, s, path="$"):
    if kind(value) not in s["kinds"]:
        return [f"{path}: {kind(value)} not in {sorted(s['kinds'])}"]
    if value is not None and s["date"] and not dated(value):
        return [f"{path}: {value!r} is not an ISO date with an offset"]
    if isinstance(value, dict):
        if value.keys() != s["keys"].keys():
            return [f"{path}: keys {sorted(value.keys() ^ s['keys'].keys())} differ"]
        return [m for k in value for m in mismatches(value[k], s["keys"][k], f"{path}.{k}")]
    if isinstance(value, list) and s["items"]:
        return [m for i, x in enumerate(value) for m in mismatches(x, s["items"], f"{path}[{i}]")]
    return []


class Snapshot(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.addCleanup(lambda: (os.environ.pop("TZ") if tz is None else os.environ.update(TZ=tz), time.tzset()))
        for patcher in (patch.object(names, "STATE_DIR", temp.name), patch.object(db, "DB", f"{temp.name}/state.db")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(db.close)
        self.prs = script()

    def snap(self):
        return snapshot.build(self.prs, snapshot.read(self.prs), RUNTIME)

    def items(self):
        return {i["key"]: i for i in self.snap()["items"]}

    def test_render_equals_the_old_show(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rq.show(self.prs)
        self.assertEqual(out.getvalue(), (FIXTURES / "show-golden.txt").read_text())

    def test_one_item_per_group_row_across_both_repos(self):
        got = {k: (i["group"], i["status"], i["detail"]) for k, i in self.items().items()}
        self.assertEqual(got, {
            "iprally/iprally#10": ("active", "reviewing", "since 12:01:02"),
            "iprally/iprally#11": ("queued", "queued", "pushed Sun 10:00"),
            "iprally/iprally#12": ("queued", "queued", "pushed Sun 10:00"),
            "iprally/iprally#13": ("ready", "ready", "quality notes only"),
            "iprally/iprally#14": ("ready", "ready", "fix refuted-only"),
            "iprally/iprally#15": ("idle", "posted", "fix queued"),
            "iprally/iprally#16": ("idle", "failed", "2026-10-25 10:00:00"),
            "iprally/iprally#18": ("idle", "new", "baseline on next run"),
            "iprally/iprally#19": ("idle", "held", "--next 19 to review"),
            "iprally/iprally#20": ("idle", "skipped", rq.NO_REVIEW),
            "iprally/iprally#22": ("ready", "ready", "2026-10-25 10:00:00"),
            "iprally/gitops#10": ("idle", "skipped", rq.NO_REVIEW),
            "iprally/gitops#21": ("active", "fixing", "since 12:05:00")})

    def test_order_ranks_and_counts(self):
        snap = self.snap()
        self.assertEqual([(i["key"], i["rank"]) for i in snap["items"][:5]],
                         [("iprally/iprally#10", None), ("iprally/gitops#21", None),
                          ("iprally/iprally#12", 1), ("iprally/iprally#11", 2), ("iprally/iprally#14", None)])
        self.assertEqual(snap["counts"], {"active": 2, "queued": 2, "ready": 3, "idle": 6, "paused": 0})
        self.assertEqual(snap["lanes"]["pools"],
                         [{"id": "review", "lane": "review", "repo": None, "workers": 3, "busy": 1, "pending": 2},
                          {"id": "fix", "lane": "fix", "repo": None, "workers": 3, "busy": 1, "pending": 4}])
        self.assertEqual([(p["repo"], p["review"], p["fix"], p["prs"]) for p in snap["projects"]],
                         [(MONOREPO, True, True, 12), (GITOPS, False, True, 2)])

    def test_a_paused_pr_goes_last_and_a_live_run_stays_active(self):
        db.pause_pr(MONOREPO, 10, True)
        db.pause_pr(MONOREPO, 11, True)
        snap = self.snap()
        items = {i["key"]: (i["group"], i["status"], i["paused"]) for i in snap["items"]}
        self.assertEqual((items["iprally/iprally#10"], items["iprally/iprally#11"]),
                         (("active", "reviewing", True), ("paused", "paused", True)))
        self.assertEqual((snap["items"][-1]["key"], snap["counts"]["paused"]), ("iprally/iprally#11", 1))

    def test_findings_rank_the_worst_three_across_reviewers(self):
        f = self.items()["iprally/iprally#10"]["findings"]
        self.assertEqual((f["head"], f["current"], f["round"], f["at_floor"]), (OLD, False, 1, 4))
        self.assertEqual([(t["reviewer"], t["severity"]) for t in f["top"]],
                         [("opus", "high"), ("opus", "medium"), ("codex", "medium")])
        self.assertEqual([(r["id"], r["result"], r["label"]) for r in f["reviewers"]],
                         [("opus", "posted", "Claude Opus 5.5"), ("codex", "posted", "Codex"),
                          ("quality", "clean", "Claude Haiku 5.5 · quality self-review")])

    def test_a_reviewer_only_the_pr_override_adds_shows_in_the_digest(self):
        extra = {**config.DEFAULTS["review"]["reviewers"][0], "id": "x", "label": "Extra"}
        db.put_pr_override(MONOREPO, 10, {"review": {"reviewers": [*config.DEFAULTS["review"]["reviewers"], extra]}})
        db.put_reviewer_result(MONOREPO, 10, OLD, "x", {"result": "clean", "engine": "claude", "round": 1,
                                                        "digest": digest()})
        items = self.items()
        self.assertEqual([r["id"] for r in items["iprally/iprally#10"]["findings"]["reviewers"]],
                         ["opus", "codex", "quality", "x"])
        self.assertEqual([r["id"] for r in items["iprally/iprally#13"]["findings"]["reviewers"]], ["quality"])

    def test_failed_reviewers_come_from_the_review_status(self):
        f = self.items()["iprally/iprally#16"]["findings"]
        self.assertEqual([(r["id"], r["result"], r["engine"]) for r in f["reviewers"]],
                         [("opus", "failed", "claude"), ("codex", "clean", "codex"), ("quality", "failed", "claude")])
        self.assertIsNone(self.items()["iprally/iprally#11"]["findings"])

    def test_active_runs_carry_reviewer_progress(self):
        items = self.items()
        self.assertEqual([(r["id"], r["state"], r["attempt"]) for r in items["iprally/iprally#10"]["active"]["reviewers"]],
                         [("opus", "running", 1), ("codex", "waiting", 2)])
        self.assertEqual(items["iprally/gitops#21"]["active"], {"lane": "fix", "since": "2026-10-25T12:05:00+00:00",
                                                                "reviewers": None})

    def test_review_and_fix_rows(self):
        items = self.items()
        self.assertEqual(items["iprally/iprally#14"]["review"],
                         {"sha": HEAD, "current": True, "status": "posted", "verdict": "posted", "note": "opus",
                          "rounds": 1, "hold": False, "at": "2026-10-25T10:00:00+00:00"})
        self.assertEqual((items["iprally/iprally#15"]["fix"]["parked"], items["iprally/iprally#15"]["fix_queued"]),
                         (True, True))
        self.assertEqual(items["iprally/iprally#13"]["author"], "ghost")

    def test_prs_of_a_repo_without_a_checkout_stay_listed_as_skipped(self):
        prs = self.prs + [item(3, "acme/site", mine=False, requested=True)]
        state = snapshot.read(prs)
        state["checkouts"] = {k: v for k, v in state["checkouts"].items() if k != GITOPS}
        with patch.dict(rq.CHECKOUTS.found, clear=True, **{MONOREPO: state["checkouts"][MONOREPO]}):
            snap = snapshot.build(prs, state, RUNTIME)
        items = {i["key"]: (i["group"], i["status"], i["detail"]) for i in snap["items"]}
        self.assertEqual((items["acme/site#3"], items["iprally/gitops#10"]),
                         (("idle", "skipped", "no checkout"), ("idle", "skipped", "no checkout")))
        self.assertEqual([(p["repo"], p["status"], p["prs"]) for p in snap["projects"]],
                         [(MONOREPO, "active", 12), (GITOPS, "no-checkout", 2), ("acme/site", "no-checkout", 1)])

    def test_rev_ignores_generated_at_and_follows_the_state(self):
        a, b = self.snap(), self.snap()
        self.assertEqual(a["rev"], b["rev"])
        self.assertEqual(len(a["rev"]), 16)
        db.drop_next(MONOREPO, 12)
        self.assertNotEqual(self.snap()["rev"], a["rev"])

    def test_the_output_has_the_shape_of_the_api_fixture(self):
        fixture = json.loads((FIXTURES / "api/v1/queue.json").read_text())
        snap = self.snap()
        top = spec([fixture])
        self.assertEqual(snap.keys(), fixture.keys())
        problems = mismatches({k: v for k, v in snap.items() if k not in ("items", "projects")},
                              spec([{k: v for k, v in fixture.items() if k not in ("items", "projects")}]))
        problems += [m for i, x in enumerate(snap["items"]) for m in mismatches(x, top["keys"]["items"]["items"],
                                                                                f"items[{i}]")]
        problems += [m for i, x in enumerate(snap["projects"])
                     for m in mismatches(x, top["keys"]["projects"]["items"], f"projects[{i}]")]
        self.assertEqual(problems, [])


class Progress(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(db, "DB", f"{temp.name}/state.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db.close)
        rq.in_review(MONOREPO, 5, True)

    def steps(self):
        return [(s["id"], s["state"], s["attempt"]) for s in db.live_runs(MONOREPO)[5]["reviewers"]]

    def run_reviewer(self, reviewer, *outs):
        seen = []
        runs = iter(CompletedProcess([], code, out, err) for code, out, err in outs)
        with patch.object(rq.subprocess, "run", side_effect=lambda *a, **k: next(runs)), \
                patch.object(rq.time, "sleep", side_effect=lambda s: seen.append(self.steps())), \
                contextlib.redirect_stdout(io.StringIO()):
            rq.run_reviewer(MONOREPO, 5, reviewer)
        return seen

    def test_a_retry_waits_then_runs_the_next_attempt(self):
        clean = json.dumps({"stop": True, "reason": "no-findings", "summary": "x" * 50})
        waits = self.run_reviewer("codex", (1, "", "boom"), (0, clean, ""))
        self.assertEqual(waits, [[("codex", "waiting", 2)]])
        self.assertEqual(self.steps(), [("codex", "clean", 2)])

    def test_each_reviewer_keeps_its_own_step_in_order(self):
        self.run_reviewer("quality", (0, json.dumps({"stop": False, "posted": True}), ""))
        self.run_reviewer("opus", *[(1, "", "boom")] * rq.ATTEMPTS)
        self.run_reviewer("codex", (1, "", "both at their usage limit"))
        self.assertEqual(self.steps(), [("opus", "failed", 3), ("codex", "limited", 1), ("quality", "posted", 1)])


if __name__ == "__main__":
    unittest.main()
