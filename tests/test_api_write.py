import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from prs import GITOPS, HEAD, MONOREPO, pr, rq
from test_api_read import fixture
from pr_wizard import api, config, db, pools

OLD = "b" * 40


def call(sock, method, path, body=None, raw=None):
    data = raw if raw is not None else b"" if body is None else json.dumps(body).encode()
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(sock)
        s.sendall(f"{method} {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
        reply = b"".join(iter(lambda: s.recv(65536), b""))
    head, payload = reply.split(b"\r\n\r\n", 1)
    return int(head.split()[1]), json.loads(payload)


class Writes(unittest.TestCase):
    prs = [pr(10), pr(12, approvals=[True]), pr(13), pr(14), pr(15), pr(16, mine=False), pr(17, labels=["no-auto-fix"]),
           pr(20, repo=GITOPS)]

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])
        self.real = f"{self.dir}/chezmoi/.pr-wizard/config.json"
        self.path = f"{self.dir}/config/config.json"
        os.makedirs(os.path.dirname(self.path))
        os.makedirs(os.path.dirname(self.real))
        os.symlink(self.real, self.path)
        for patcher in (patch.dict(os.environ, {"PR_WIZARD_CONFIG": self.path}),
                        patch.object(db, "DB", f"{self.dir}/state.db"), patch.object(rq, "worker"),
                        patch.object(rq, "say")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(db.close)
        self.rt = rq.Runtime()
        self.rt.refreshed([dict(p, updatedAt=p["commits"]["nodes"][0]["commit"]["committedDate"]) for p in self.prs])
        self.pools = pools.Pools()
        self.rt.attach(self.pools)
        self.rt.apply()
        self.sock = f"{self.dir}/api.sock"
        server = api.bind(self.rt, self.sock)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def call(self, method, path, body=None, raw=None):
        return call(self.sock, method, path, body, raw)

    def write(self, doc):
        with open(self.real, "w") as fh:
            json.dump(config.merge(config.DEFAULTS, doc), fh)
        self.assertIsNone(rq.SETTINGS.get().error)

    def refetched(self):
        return self.rt.refresh_now.is_set() and not self.rt.refresh_now.clear()


class Config(Writes):
    def rev(self):
        return self.call("GET", "/v1/config")[1]["rev"]

    def test_put_saves_through_the_symlink_and_applies_at_once(self):
        status, body = self.call("PUT", "/v1/config", {"base_rev": self.rev(), "config": {"review": {"workers": 2}}})
        self.assertEqual((status, body["source"], body["config"]["review"]["workers"]), (200, "file", 2))
        self.assertEqual(body["config"], config.merge(config.DEFAULTS, {"review": {"workers": 2}}))
        self.assertTrue(os.path.islink(self.path))
        with open(self.real) as fh:
            self.assertEqual(json.load(fh), body["config"])
        self.assertEqual((body["path"], body["real_path"]), (self.path, os.path.realpath(self.real)))
        self.assertEqual(self.pools.sizes(), {"review": 2, "fix": 3})
        self.assertTrue(self.refetched())

    def test_put_without_base_rev_replaces_the_whole_document(self):
        self.write({"fix": {"workers": 1}})
        body = self.call("PUT", "/v1/config", {"config": {"review": {"workers": 2}}})[1]
        self.assertEqual((body["config"]["review"]["workers"], body["config"]["fix"]["workers"]), (2, 3))

    def test_patch_merges_and_null_goes_back_to_the_default(self):
        self.write({"review": {"workers": 2}})
        body = self.call("PATCH", "/v1/config", {"base_rev": self.rev(), "patch": {"fix": {"workers": 1}}})[1]
        self.assertEqual((body["config"]["review"]["workers"], body["config"]["fix"]["workers"]), (2, 1))
        body = self.call("PATCH", "/v1/config", {"patch": {"review": {"workers": None}}})[1]
        self.assertEqual((body["config"]["review"]["workers"], body["config"]["fix"]["workers"]), (3, 1))
        self.assertEqual(self.pools.sizes(), {"review": 3, "fix": 1})

    def test_a_stale_base_rev_is_412_and_saves_nothing(self):
        status, body = self.call("PATCH", "/v1/config", {"base_rev": "0" * 12, "patch": {"fix": {"workers": 1}}})
        self.assertEqual((status, body["error"]["code"]), (412, "stale_config"))
        self.assertFalse(os.path.exists(self.real))

    def test_invalid_config_is_422_with_every_problem_in_bracket_paths(self):
        status, body = self.call("PATCH", "/v1/config", {"patch": {"review": {"workers": 0}, "projects": {
            GITOPS: {"fix": {"workers": 9}}}}})
        like = fixture("error-invalid-config")["error"]
        self.assertEqual(status, 422)
        self.assertEqual({**body["error"], "details": sorted(body["error"]["details"], key=str)},
                         {**like, "details": sorted(like["details"], key=str)})
        self.assertFalse(os.path.exists(self.real))

    def test_unknown_keys_are_422(self):
        status, body = self.call("PUT", "/v1/config", {"config": {"review": {"nope": 1}}})
        self.assertEqual((status, body["error"]["message"], body["error"]["details"]),
                         (422, "1 problem in the config", [{"path": "review.nope", "message": "unknown key"}]))

    def test_a_body_over_1_mib_is_413(self):
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(self.sock)
            s.sendall(f"PUT /v1/config HTTP/1.1\r\nContent-Length: {api.MAX_BODY + 1}\r\n\r\n".encode())
            reply = b"".join(iter(lambda: s.recv(65536), b""))
        self.assertEqual(json.loads(reply.split(b"\r\n\r\n", 1)[1]),
                         api.error("payload_too_large", f"the body is over {api.MAX_BODY} bytes"))
        self.assertIn(b" 413 ", reply.split(b"\r\n")[0])

    def test_malformed_bodies_are_400(self):
        for raw in (b"{", b"[]", b'{"config": 1}', b'{"config": {}, "base_rev": 1}'):
            self.assertEqual(self.call("PUT", "/v1/config", raw=raw)[1]["error"]["code"], "bad_request", raw)


class Next(Writes):
    def bump(self, *prs, only_queued=None):
        body = {"prs": [{"repo": r, "number": n} for r, n in prs]}
        return self.call("POST", "/v1/next", body if only_queued is None else {**body, "only_queued": only_queued})

    def setUp(self):
        super().setUp()
        db.run_start(MONOREPO, 13, "review")
        db.put_review(MONOREPO, 14, {"sha": HEAD, "status": "clean", "verdict": "clean"})
        db.put_review(MONOREPO, 15, {"sha": OLD, "status": "clean", "verdict": "clean", "hold": True})

    def test_every_reason(self):
        status, body = self.bump(("acme/nope", 1), (MONOREPO, 11), (MONOREPO, 12), (GITOPS, 20), (MONOREPO, 13),
                                 (MONOREPO, 14), (MONOREPO, 15), (MONOREPO, 10))
        self.assertEqual(status, 200)
        self.assertEqual([(r["key"], r["bumped"], r["reason"]) for r in body["results"]], [
            ("acme/nope#1", False, "unknown-repo"), (f"{MONOREPO}#11", False, "not-in-queue"),
            (f"{MONOREPO}#12", False, "not-in-queue"), (f"{GITOPS}#20", False, "review-lane-off"),
            (f"{MONOREPO}#13", False, "active"), (f"{MONOREPO}#14", False, "nothing-new"),
            (f"{MONOREPO}#15", True, None), (f"{MONOREPO}#10", True, None)])
        self.assertEqual(body["next"], [f"{MONOREPO}#15", f"{MONOREPO}#10"])
        self.assertEqual(db.next_list(MONOREPO), [15, 10])
        self.assertTrue(self.refetched())

    def test_the_first_listed_ends_up_first(self):
        self.bump((MONOREPO, 10))
        self.assertEqual(self.bump((MONOREPO, 15), (MONOREPO, 10))[1]["next"], [f"{MONOREPO}#15", f"{MONOREPO}#10"])

    def test_nothing_bumped_refetches_nothing(self):
        self.assertEqual(self.bump((MONOREPO, 14))[1]["next"], [])
        self.assertFalse(self.refetched())

    def test_only_queued_false_prepends_every_known_pr_as_given(self):
        body = self.bump((MONOREPO, 14), (MONOREPO, 11), ("acme/nope", 1), only_queued=False)[1]
        self.assertEqual([r["reason"] for r in body["results"]], [None, None, "unknown-repo"])
        self.assertEqual(body["next"], [f"{MONOREPO}#14", f"{MONOREPO}#11"])

    def test_a_bad_body_is_400(self):
        for body in ({}, {"prs": []}, {"prs": [{"repo": MONOREPO, "number": n} for n in range(21)]},
                     {"prs": [{"repo": MONOREPO, "number": "1"}]}, {"prs": [{"repo": MONOREPO, "number": 1}],
                                                                    "only_queued": "no"}):
            self.assertEqual(self.call("POST", "/v1/next", body)[1]["error"]["code"], "bad_request", body)


class Actions(Writes):
    def act(self, repo, n, lane):
        return self.call("POST", f"/v1/prs/{repo}/{n}/{lane}")

    def code(self, repo, n, lane):
        status, body = self.act(repo, n, lane)
        return status, body["error"]["code"]

    def test_review_now_runs_beside_the_pools_even_while_paused(self):
        self.rt.pause(True)
        with patch.object(rq, "review_now") as review_now:
            self.assertEqual(self.act(MONOREPO, 17190, "review"), (202, fixture("accepted")))
        review_now.assert_called_once_with(MONOREPO, 17190)

    def test_review_now_refusals(self):
        db.run_start(MONOREPO, 13, "fix")
        self.write({"projects": {"acme/widgets": {}}})
        with patch.object(rq, "review_now") as review_now:
            self.assertEqual(self.code("acme/nope", 1, "review"), (404, "unknown_repo"))
            self.assertEqual(self.code("acme/widgets", 1, "review"), (409, "no_checkout"))
            self.assertEqual(self.code(GITOPS, 20, "review"), (409, "review_lane_off"))
            self.assertEqual(self.act(MONOREPO, 13, "review"),
                             (409, api.error("busy", f"a live run already holds {MONOREPO}#13")))
        review_now.assert_not_called()

    def test_fix_rearms_a_parked_pass_and_refetches(self):
        db.put_fix(MONOREPO, 10, {"sha": HEAD, "key": "k", "status": "error", "errors": 3})
        self.assertEqual(self.act(MONOREPO, 10, "fix"), (202, {"key": f"{MONOREPO}#10", "accepted": True}))
        self.assertEqual({k: db.fix(MONOREPO, 10)[k] for k in ("key", "errors", "status")},
                         {"key": None, "errors": 0, "status": "error"})
        self.assertTrue(self.refetched())

    def test_fix_refusals(self):
        db.run_start(MONOREPO, 13, "review")
        self.assertEqual(self.code("acme/nope", 1, "fix"), (404, "unknown_repo"))
        self.assertEqual(self.code(MONOREPO, 11, "fix"), (404, "not_in_queue"))
        self.assertEqual(self.code(MONOREPO, 16, "fix"), (409, "not_mine"))
        self.assertEqual(self.code(MONOREPO, 17, "fix"), (409, "no_auto_fix"))
        self.assertEqual(self.code(MONOREPO, 13, "fix"), (409, "busy"))
        self.write({"projects": {GITOPS: {"fix": {"enabled": False}}}})
        self.assertEqual(self.code(GITOPS, 20, "fix"), (409, "fix_lane_off"))
        self.assertFalse(self.refetched())

    def test_refresh_is_accepted_and_refetches(self):
        self.assertEqual(self.call("POST", "/v1/refresh"), (202, {"accepted": True}))
        self.assertTrue(self.refetched())


class Pause(Writes):
    def paused(self, lanes):
        return [p.paused for p in lanes.pools.values()]

    def test_pause_and_resume_flip_the_snapshot_and_the_pools_and_survive_a_restart(self):
        self.assertEqual(self.call("POST", "/v1/pause"), (200, fixture("paused")))
        self.assertTrue(self.call("GET", "/v1/queue")[1]["paused"])
        self.assertEqual(self.paused(self.pools), [True, True])
        restarted = pools.Pools()
        rq.Runtime().attach(restarted)
        restarted.apply(rq.cfg(), [])
        self.assertEqual(self.paused(restarted), [True, True])
        self.assertEqual(self.call("POST", "/v1/resume"), (200, {"paused": False}))
        self.assertEqual((self.call("GET", "/v1/info")[1]["paused"], self.paused(self.pools)),
                         (False, [False, False]))

    def test_a_paused_pool_lets_the_running_pass_finish_and_takes_no_new_pr(self):
        started, release, ran, done = threading.Event(), threading.Event(), threading.Semaphore(0), []
        pending = rq.Pending([pr(1), pr(2)], 1)
        pending.live = 1

        def job(p, first):
            started.set()
            release.wait(5)
            done.append(p["number"])
            ran.release()

        with patch.object(rq, "bumps", return_value={MONOREPO: []}), patch.object(rq, "claimed") as claimed:
            claimed.return_value.__enter__.return_value = True
            thread = threading.Thread(target=rq.work, args=(pending, True, job), daemon=True)
            thread.start()
            self.assertTrue(started.wait(5))
            pending.pause(True)
            release.set()
            thread.join(0.3)
            self.assertEqual((done, [p["number"] for p in pending.prs]), ([1], [2]))
            pending.pause(False)
            self.assertTrue(ran.acquire(timeout=5) and ran.acquire(timeout=5))
            pending.resize(0, list)
            thread.join(5)
        self.assertEqual(done, [1, 2])
