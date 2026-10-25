import random
import threading
import time
import unittest
from unittest.mock import patch

from prs import GITOPS, MONOREPO, pr, rq
from test_queue_config import Configured
from pr_wizard import config, pools, snapshot

NEW = "acme/widgets"
LISTING = [{"repo": MONOREPO, "review": True, "fix": True}, {"repo": GITOPS, "review": False, "fix": True}]
SHARED = {"review": 3, "fix": 3}
SEPARATE = {f"review:{MONOREPO}": 3, f"fix:{MONOREPO}": 3, f"fix:{GITOPS}": 3}


def cfg(separate=False, **projects):
    return config.merge(config.DEFAULTS, {"lanes": {"separate": separate}, "projects": projects})


class Lanes(unittest.TestCase):
    def setUp(self):
        self.ran, self.gate, self.lock = [], threading.Event(), threading.Lock()
        self.gate.set()
        self.threads = []
        for patcher in (patch.object(rq, "bumps", return_value={}), patch.object(rq, "claimed"),
                        patch.object(pools, "spawn", self.spawn)):
            started = patcher.start()
            self.addCleanup(patcher.stop)
            if patcher.attribute == "claimed":
                started.return_value.__enter__.return_value = True
        self.lanes = pools.Pools()
        self.addCleanup(self.stop)

    def spawn(self, lane, pool):
        thread = rq.worker(pool, True, lambda p, first: self.job(pool, p))
        self.threads.append(thread)
        return thread

    def job(self, pool, p):
        with self.lock:
            self.ran.append((pool, rq.pr_key(p)))
        self.gate.wait(5)

    def stop(self):
        self.gate.set()
        self.lanes.apply(cfg(separate=True), [])
        for t in self.threads:
            t.join(5)

    def until(self, check):
        deadline = time.monotonic() + 5
        while not check():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def keys(self):
        with self.lock:
            return [key for _, key in self.ran]

    def pool(self, lane, repo=None):
        return self.lanes.pools[lane, repo]


class Switch(Lanes):
    def test_on_keeps_the_running_pass_in_its_old_pool_and_hands_it_out_after(self):
        self.lanes.apply(cfg(), LISTING)
        self.assertEqual(self.lanes.sizes(), SHARED)
        shared = self.pool("review")
        self.gate.clear()
        self.lanes.refill("review", [pr(1)])
        self.until(lambda: self.keys() == [(MONOREPO, 1)])
        self.lanes.apply(cfg(separate=True), LISTING)
        self.assertEqual(self.lanes.sizes(), SEPARATE)
        self.lanes.refill("review", [pr(1), pr(2)])
        self.until(lambda: len(self.keys()) == 2)
        self.assertEqual(self.ran[1], (self.pool("review", MONOREPO), (MONOREPO, 2)))
        self.assertEqual(self.pool("review", MONOREPO).prs, [])
        self.gate.set()
        self.until(lambda: shared.live == 0)
        self.lanes.refill("review", [pr(1)])
        self.until(lambda: self.ran[-1] == (self.pool("review", MONOREPO), (MONOREPO, 1)))

    def test_off_retires_every_project_pool_and_routes_all_repos_to_the_shared_ones(self):
        self.lanes.apply(cfg(separate=True), LISTING)
        old = list(self.lanes.pools.values())
        self.lanes.apply(cfg(), LISTING)
        self.until(lambda: all(p.live == 0 for p in old))
        self.assertEqual(self.lanes.sizes(), SHARED)
        self.lanes.refill("fix", [pr(1), pr(1, repo=GITOPS)])
        self.until(lambda: sorted(self.keys()) == [(GITOPS, 1), (MONOREPO, 1)])
        self.assertEqual({pool for pool, _ in self.ran}, {self.pool("fix")})

    def test_a_pr_without_a_pool_of_its_lane_waits_in_none(self):
        self.lanes.apply(cfg(separate=True), LISTING)
        self.lanes.refill("review", [pr(1, repo=GITOPS)])
        self.assertEqual(self.pool("review", MONOREPO).prs, [])

    def test_a_paused_set_starts_its_new_pools_paused(self):
        self.lanes.pause(True)
        self.lanes.apply(cfg(separate=True), LISTING)
        self.assertTrue(all(p.paused for p in self.lanes.pools.values()))


class Projects(Lanes):
    def test_each_project_pool_takes_its_effective_worker_counts(self):
        self.lanes.apply(cfg(True, **{MONOREPO: {"review": {"workers": 2}}, GITOPS: {"fix": {"workers": 1}}}), LISTING)
        self.assertEqual(self.lanes.sizes(), {f"review:{MONOREPO}": 2, f"fix:{MONOREPO}": 3, f"fix:{GITOPS}": 1})
        self.assertEqual(self.pool("review", MONOREPO).live, 2)

    def test_the_shared_pools_ignore_the_project_counts(self):
        self.lanes.apply(cfg(False, **{MONOREPO: {"review": {"workers": 2}}}), LISTING)
        self.assertEqual(self.lanes.sizes(), SHARED)

    def test_a_project_that_appears_gets_pools_and_one_that_goes_retires_them(self):
        self.lanes.apply(cfg(separate=True), LISTING)
        self.lanes.apply(cfg(separate=True), LISTING + [{"repo": NEW, "review": True, "fix": False}])
        self.assertEqual(self.lanes.sizes(), {**SEPARATE, f"review:{NEW}": 3})
        new = self.pool("review", NEW)
        self.gate.clear()
        self.lanes.refill("review", [pr(1, repo=NEW)])
        self.until(lambda: self.keys() == [(NEW, 1)])
        self.lanes.apply(cfg(separate=True), LISTING)
        self.until(lambda: new.live == 1)
        self.assertEqual((self.lanes.sizes(), new.busy), (SEPARATE, {(NEW, 1)}))
        self.gate.set()
        self.until(lambda: new.live == 0)


class Storm(Lanes):
    def test_fifty_prs_through_live_switches_and_refills_are_never_claimed_twice_nor_lost(self):
        prs = [pr(n, repo=random.choice([MONOREPO, GITOPS, NEW])) for n in range(50)]
        listing = LISTING + [{"repo": NEW, "review": True, "fix": True}]
        running, twice, done = set(), [], set()
        self.gate.clear()

        def job(pool, p):
            key = rq.pr_key(p)
            with self.lock:
                twice.extend([key] if key in running else [])
                running.add(key)
            time.sleep(random.random() / 200)
            with self.lock:
                running.discard(key)
                done.add(key)

        self.job = job
        rng = random.Random(7)
        for _ in range(300):
            if rng.random() < 0.2:
                self.lanes.apply(cfg(rng.random() < 0.5, **{NEW: {"review": {"workers": rng.randint(1, 4)}}}),
                                 rng.sample(listing, rng.randint(1, 3)))
            self.lanes.refill(rng.choice(pools.LANES), rng.sample(prs, rng.randint(0, 50)))
            time.sleep(rng.random() / 1000)
        self.lanes.apply(cfg(), listing)
        while len(done) < 50:
            self.lanes.refill("fix", [p for p in prs if rq.pr_key(p) not in done])
            self.until(lambda: not self.pool("fix").prs)
        self.lanes.apply(cfg(separate=True), [])
        self.until(lambda: not self.lanes.held)
        self.assertEqual((twice, len(done)), ([], 50))


class Snapshot(Configured):
    def snap(self, prs):
        prs = [dict(p, updatedAt=p["commits"]["nodes"][0]["commit"]["committedDate"]) for p in prs]
        return snapshot.build(prs, snapshot.read(prs), {"generated_at": None, "fetched_at": None, "paused": False,
                                                        "refresh": {}})

    def test_separate_pools_count_their_own_repo(self):
        self.write({"lanes": {"separate": True}, "projects": {GITOPS: {"fix": {"workers": 1}}}})
        lanes = self.snap([pr(1), pr(2), pr(3, repo=GITOPS, mine=False)])["lanes"]
        self.assertEqual(lanes, {"separate": True, "pools": [
            {"id": f"review:{MONOREPO}", "lane": "review", "repo": MONOREPO, "workers": 3, "busy": 0, "pending": 2},
            {"id": f"fix:{MONOREPO}", "lane": "fix", "repo": MONOREPO, "workers": 3, "busy": 0, "pending": 0},
            {"id": f"fix:{GITOPS}", "lane": "fix", "repo": GITOPS, "workers": 1, "busy": 0, "pending": 0}]})

    def test_shared_pools_count_every_repo(self):
        self.write({"projects": {GITOPS: {"review": {"enabled": True}}}})
        lanes = self.snap([pr(1), pr(2, repo=GITOPS)])["lanes"]
        self.assertEqual(lanes["separate"], False)
        self.assertEqual([(p["id"], p["repo"], p["pending"]) for p in lanes["pools"]],
                         [("review", None, 2), ("fix", None, 0)])
