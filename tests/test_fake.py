import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_wizard import api, config, fake

IPRALLY, GITOPS, SITE = "iprally/iprally", "iprally/gitops", "clojure/clojurescript-site"


def fixture(name):
    return json.loads((Path(fake.FIXTURES) / f"{name}.json").read_text())


def call(sock, method, path, body=None):
    data = b"" if body is None else json.dumps(body).encode()
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(sock)
        s.sendall(f"{method} {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
        reply = b"".join(iter(lambda: s.recv(65536), b""))
    head, payload = reply.split(b"\r\n\r\n", 1)
    return int(head.split()[1]), json.loads(payload)


class Fake(unittest.TestCase):
    speed = 0

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])
        self.rt = fake.Runtime(speed=self.speed, epoch="ke1")
        self.sock = f"{self.dir}/fake.sock"
        server = api.bind(self.rt, self.sock)
        threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def call(self, method, path, body=None):
        return call(self.sock, method, path, body)

    def item(self, key):
        return next(i for i in self.call("GET", "/v1/queue")[1]["items"] if i["key"] == key)

    def keys(self):
        return [i["key"] for i in self.call("GET", "/v1/queue")[1]["items"]]

    def patch(self, patch_):
        return self.call("PATCH", "/v1/config", {"patch": patch_})

    def inject(self, number, **fields):
        """A copy of the queued PR 17201 as another PR, for the cases the fixture has one of."""
        with self.rt.lock:
            item = copy.deepcopy(next(i for i in self.rt.snap["items"] if i["number"] == 17201))
            item.update(number=number, key=f"{IPRALLY}#{number}", bumped=False, **fields)
            self.rt.snap["items"].append(item)
            self.rt.publish()
        return item["key"]


class Flags(unittest.TestCase):
    def runtime(self, *argv, **env):
        taken = []
        with patch.object(sys, "argv", ["api", "--fake", *argv]), patch.dict(os.environ, env), \
                patch.object(api, "bind", side_effect=lambda rt, path: taken.append(rt) or sys.exit(0)):
            with self.assertRaises(SystemExit):
                api.main()
        return taken[0]

    def test_the_flags_set_the_knobs(self):
        rt = self.runtime("--fake-speed", "0", "--fake-empty")
        self.assertEqual((rt.speed, rt.snapshot()["items"]), (0, []))

    def test_the_env_vars_still_work(self):
        rt = self.runtime(PRW_FAKE_SPEED="2", PRW_FAKE_EMPTY="1")
        self.assertEqual((rt.speed, rt.snapshot()["items"]), (2, []))

    def test_a_flag_beats_the_env_var(self):
        self.assertEqual(self.runtime("--fake-speed", "0", PRW_FAKE_SPEED="2").speed, 0)


class Reads(Fake):
    def test_the_first_responses_are_the_fixtures(self):
        for path, name in (("/v1/queue", "queue"), ("/v1/info", "info"), ("/v1/config", "config")):
            self.assertEqual(self.call("GET", path)[1], fixture(name), path)
        self.assertEqual(self.call("GET", "/v1/history")[1], {"entries": fixture("history")["entries"]})

    def test_history_takes_a_limit_and_a_repo(self):
        self.assertEqual(self.call("GET", "/v1/history?repo=iprally/gitops")[1], {"entries": []})
        self.assertEqual(len(self.call("GET", "/v1/history?limit=1")[1]["entries"]), 1)
        self.assertEqual(self.call("GET", "/v1/history?limit=0")[0], 400)

    def test_an_empty_queue_keeps_the_history(self):
        rt = fake.Runtime(speed=0, empty=True)
        self.assertEqual((rt.snapshot()["items"], rt.snapshot()["counts"]), ([], dict.fromkeys(fake.GROUPS, 0)))
        self.assertEqual(len(rt.history(None, 20)["entries"]), 1)

    def test_the_events_cursor(self):
        status, first = self.call("GET", "/v1/events")
        self.assertEqual((status, first["events"], first["reset"], first["cursor"]), (200, [], False, "ke1.58"))
        self.assertEqual(self.call("GET", "/v1/events?since=ke1.57")[1]["events"][0]["seq"], 58)
        for stale in ("other.58", "ke1.3", "junk"):
            page = self.call("GET", f"/v1/events?since={stale}")[1]
            self.assertEqual((page["reset"], [e["seq"] for e in page["events"]]), (True, [57, 58]), stale)


class Config(Fake):
    def rev(self):
        return self.call("GET", "/v1/config")[1]["rev"]

    def test_put_keeps_the_config_in_memory_and_everything_follows(self):
        before = self.call("GET", "/v1/queue")[1]
        with patch.object(config, "save") as save:
            status, body = self.call("PUT", "/v1/config", {"base_rev": self.rev(), "config": {"review": {"workers": 2}}})
        save.assert_not_called()
        self.assertEqual((status, body["source"], body["config"]["review"]["workers"]), (200, "file", 2))
        self.assertEqual(body["rev"], config.rev(body["config"]))
        self.assertEqual(self.call("GET", "/v1/config")[1], body)
        self.assertEqual(body["effective"][IPRALLY]["review"]["workers"], 2)
        queue = self.call("GET", "/v1/queue")[1]
        self.assertNotEqual(queue["rev"], before["rev"])
        self.assertEqual([p["workers"] for p in queue["lanes"]["pools"]], [2, 3])
        self.assertEqual(self.call("GET", "/v1/info")[1]["config"]["rev"], body["rev"])

    def test_patch_turns_lanes_off_and_the_projects_follow(self):
        self.assertEqual(self.patch({"projects": {GITOPS: {"fix": {"enabled": False}}}})[0], 200)
        project = {p["repo"]: p for p in self.call("GET", "/v1/queue")[1]["projects"]}[GITOPS]
        self.assertEqual((project["status"], project["review"], project["fix"]), ("off", False, False))
        self.assertEqual(self.patch({"projects": {GITOPS: {"fix": None}}})[0], 200)
        project = {p["repo"]: p for p in self.call("GET", "/v1/info")[1]["projects"]}[GITOPS]
        self.assertEqual((project["status"], project["review"], project["fix"]), ("active", False, True))

    def test_separate_lanes_make_a_pool_per_project_lane(self):
        self.patch({"lanes": {"separate": True}})
        pools = self.call("GET", "/v1/queue")[1]["lanes"]["pools"]
        self.assertEqual([p["id"] for p in pools], ["review:iprally/iprally", "fix:iprally/iprally", "fix:iprally/gitops",
                                                   "review:sandudorogan/dataspex", "fix:sandudorogan/dataspex"])
        self.assertEqual(sum(p["busy"] for p in pools), 1)

    def test_a_stale_base_rev_is_412_and_changes_nothing(self):
        rev = self.rev()
        status, body = self.call("PUT", "/v1/config", {"base_rev": "0" * 12, "config": {}})
        self.assertEqual((status, body["error"]["code"]), (412, "stale_config"))
        self.assertEqual(self.rev(), rev)

    def test_an_invalid_config_is_422_with_bracket_paths_and_changes_nothing(self):
        rev = self.rev()
        status, body = self.patch({"review": {"workers": 99}, "projects": {GITOPS: {"fix": {"workers": 0}}}})
        self.assertEqual((status, body["error"]["code"]), (422, "invalid_config"))
        self.assertEqual({d["path"] for d in body["error"]["details"]}, {"review.workers", f'projects["{GITOPS}"].fix.workers'})
        self.assertEqual(self.rev(), rev)


class Actions(Fake):
    def test_refresh_appends_a_ready_event_and_moves_the_rev(self):
        before = self.call("GET", "/v1/queue")[1]
        self.assertEqual(self.call("POST", "/v1/refresh"), (202, {"accepted": True}))
        after = self.call("GET", "/v1/queue")[1]
        self.assertNotEqual(after["rev"], before["rev"])
        self.assertEqual(after["fetched_at"], after["refresh"]["last_at"])
        page = self.call("GET", "/v1/events?since=ke1.58")[1]
        [event] = page["events"]
        self.assertEqual((page["cursor"], event["seq"], event["type"], event["key"]), ("ke1.59", 59, "ready_for_approval", f"{IPRALLY}#17166"))
        self.assertEqual(event["id"], f"ready_for_approval:{IPRALLY}#17166@9f8e7d6c5b4a")

    def test_next_moves_a_queued_pr_to_the_front_and_ranks_follow(self):
        other = self.inject(17300)
        self.assertEqual([self.item(k)["rank"] for k in (f"{IPRALLY}#17201", other)], [1, 2])
        status, body = self.call("POST", "/v1/next", {"prs": [{"repo": IPRALLY, "number": 17300}]})
        self.assertEqual((status, body["next"][0], body["results"]), (200, other, [{"key": other, "bumped": True, "reason": None}]))
        self.assertEqual(self.keys()[1:3], [other, f"{IPRALLY}#17201"])
        self.assertEqual([(self.item(k)["rank"], self.item(k)["bumped"]) for k in (other, f"{IPRALLY}#17201")], [(1, True), (2, True)])

    def test_next_says_why_it_leaves_a_pr(self):
        prs = [(IPRALLY, 17166), (IPRALLY, 17190), (GITOPS, 412), ("a/b", 1), (IPRALLY, 9)]
        body = self.call("POST", "/v1/next", {"prs": [{"repo": r, "number": n} for r, n in prs]})[1]
        self.assertEqual([r["reason"] for r in body["results"]],
                         ["nothing-new", "active", "review-lane-off", "unknown-repo", "not-in-queue"])
        self.assertEqual(body["next"], [f"{IPRALLY}#17201"])

    def test_next_bumps_a_held_pr_into_the_queue_and_only_queued_false_prepends_all(self):
        held = self.inject(17301, group="idle", status="held", detail="held", rank=None)
        self.call("POST", "/v1/next", {"prs": [{"repo": IPRALLY, "number": 17301}]})
        self.assertEqual((self.item(held)["group"], self.item(held)["rank"]), ("queued", 1))
        body = self.call("POST", "/v1/next", {"prs": [{"repo": IPRALLY, "number": 17166}], "only_queued": False})[1]
        self.assertEqual((body["results"][0]["bumped"], body["next"][0]), (True, f"{IPRALLY}#17166"))
        self.assertEqual(self.call("POST", "/v1/next", {"prs": []})[0], 400)

    def test_pause_and_resume_flip_the_snapshot_and_info(self):
        for path, paused in (("pause", True), ("resume", False), ("pause", True)):
            self.assertEqual(self.call("POST", f"/v1/{path}"), (200, {"paused": paused}))
            self.assertEqual([self.call("GET", f"/v1/{p}")[1]["paused"] for p in ("queue", "info")], [paused] * 2)

    def test_review_of_a_colleague_pr_withdraws_then_reposts_the_ready_event(self):
        key = f"{IPRALLY}#17166"
        self.assertEqual(self.call("POST", f"/v1/prs/{IPRALLY}/17166/review"), (202, {"key": key, "accepted": True}))
        item = self.item(key)
        self.assertEqual((item["group"], item["status"], item["review"]["verdict"], item["active"]), ("ready", "ready", "clean", None))
        self.assertEqual({r["result"] for r in item["findings"]["reviewers"]}, {"clean"})
        events = self.call("GET", "/v1/events?since=ke1.58")[1]["events"]
        self.assertEqual([(e["type"], e["verdict"]) for e in events], [("ready_withdrawn", None), ("ready_for_approval", "clean")])
        entry = self.call("GET", "/v1/history")[1]["entries"][0]
        self.assertEqual((entry["key"], entry["outcome"], entry["state"]), (key, "ready", "settled"))

    def test_review_of_my_pr_settles_idle_clean(self):
        self.patch({"projects": {GITOPS: {"review": {"enabled": True}}}})
        self.call("POST", f"/v1/prs/{GITOPS}/412/review")
        item = self.item(f"{GITOPS}#412")
        self.assertEqual((item["group"], item["status"], item["review"]["hold"]), ("idle", "clean", True))
        self.assertEqual(self.call("GET", "/v1/history")[1]["entries"][0]["outcome"], "clean")
        self.assertEqual(self.call("GET", "/v1/events?since=ke1.58")[1]["events"], [])

    def test_review_refusals(self):
        refused = lambda repo, n: self.call("POST", f"/v1/prs/{repo}/{n}/review")[1]["error"]["code"]
        self.assertEqual(refused(IPRALLY, 17190), "busy")
        self.assertEqual(refused(GITOPS, 412), "review_lane_off")
        self.assertEqual(refused(SITE, 1), "no_checkout")
        self.assertEqual(refused("a/b", 1), "unknown_repo")

    def test_fix_runs_and_restores_the_row(self):
        before = self.item(f"{GITOPS}#412")
        self.assertEqual(self.call("POST", f"/v1/prs/{GITOPS}/412/fix"), (202, {"key": f"{GITOPS}#412", "accepted": True}))
        after = self.item(f"{GITOPS}#412")
        self.assertEqual({k: after[k] for k in ("group", "status", "detail", "active")},
                         {k: before[k] for k in ("group", "status", "detail", "active")})
        self.assertEqual((after["fix"]["status"], after["fix"]["parked"], after["fix"]["current"]), ("nothing-to-fix", False, True))

    def test_fix_refusals(self):
        self.inject(17302, labels=["no-auto-fix"], mine=True)
        refused = lambda repo, n: self.call("POST", f"/v1/prs/{repo}/{n}/fix")[1]["error"]["code"]
        self.assertEqual(refused(IPRALLY, 17190), "busy")
        self.assertEqual(refused(IPRALLY, 17166), "not_mine")
        self.assertEqual(refused(IPRALLY, 17302), "no_auto_fix")
        self.assertEqual(refused(IPRALLY, 9), "not_in_queue")
        self.assertEqual(refused("a/b", 1), "unknown_repo")
        self.patch({"projects": {GITOPS: {"fix": {"enabled": False}}}})
        self.assertEqual(refused(GITOPS, 412), "fix_lane_off")


class Waking(Fake):
    def long_poll(self, path):
        out = []
        thread = threading.Thread(target=lambda: out.append((time.monotonic(), self.call("GET", path))))
        thread.start()
        time.sleep(0.3)
        self.assertEqual(out, [])
        return thread, out

    def test_a_refresh_wakes_the_events_and_queue_polls(self):
        rev = self.call("GET", "/v1/queue")[1]["rev"]
        waiting = [self.long_poll(f"/v1/events?since=ke1.58&wait=20"), self.long_poll(f"/v1/queue?since={rev}&wait=20")]
        started = time.monotonic()
        self.call("POST", "/v1/refresh")
        for thread, out in waiting:
            thread.join(5)
            self.assertLess(out[0][0] - started, 2)
        self.assertEqual(len(waiting[0][1][0][1][1]["events"]), 1)
        self.assertNotEqual(waiting[1][1][0][1][1]["rev"], rev)

    def test_every_action_wakes_the_queue_poll(self):
        for method, path, body in (("PATCH", "/v1/config", {"patch": {"fix": {"workers": 1}}}), ("POST", "/v1/pause", None),
                                   ("POST", "/v1/next", {"prs": [{"repo": IPRALLY, "number": 17166}], "only_queued": False})):
            rev = self.call("GET", "/v1/queue")[1]["rev"]
            thread, out = self.long_poll(f"/v1/queue?since={rev}&wait=20")
            self.call(method, path, body)
            thread.join(5)
            self.assertNotEqual(out[0][1][1]["rev"], rev, path)


class Timed(Fake):
    speed = 0.8

    def test_a_review_steps_through_running_to_clean_then_ready(self):
        self.call("POST", f"/v1/prs/{IPRALLY}/17166/review")
        item = self.item(f"{IPRALLY}#17166")
        self.assertEqual((item["group"], item["status"], item["active"]["lane"]), ("active", "reviewing", "review"))
        self.assertEqual({r["state"] for r in item["active"]["reviewers"]}, {"running"})
        self.assertEqual(self.call("POST", f"/v1/prs/{IPRALLY}/17166/review")[1]["error"]["code"], "busy")
        states, rev = [], self.call("GET", "/v1/queue")[1]["rev"]
        while (item := self.item(f"{IPRALLY}#17166"))["active"]:
            states.append([r["state"] for r in item["active"]["reviewers"]])
            rev = self.call("GET", f"/v1/queue?since={rev}&wait=5")[1]["rev"]
        self.assertIn(["clean", "running", "running"], states)
        self.assertEqual(self.item(f"{IPRALLY}#17166")["group"], "ready")


if __name__ == "__main__":
    unittest.main()
