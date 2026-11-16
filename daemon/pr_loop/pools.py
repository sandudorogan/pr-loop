"""The worker pools of the one daemon (api.md §4.7): a shared review and fix pool, or with `lanes.separate` a pair per
active project. Every pool is a set of threads in this process.

  separate off                        separate on
  review ×3 ◀─ every project's PRs    review:iprally/iprally ×3 ◀─ its PRs   fix:iprally/iprally ×3
  fix    ×3 ◀─ every project's PRs    fix:iprally/gitops ×3      ◀─ its PRs   …

A switch builds the new set under the one lock all pools share: kept pools resize, new ones start, removed ones drop
their queue and retire their workers after the running pass. `held` spans every pool, so a PR that runs in a retiring
pool is never handed out by its new one.

The scope pool (`scope.workers`, 0 while `scope.enabled` is off) is always one shared pool beside them. It keeps its
own `held` and takes no per-PR lock: a scope pass reads the PR and never holds up its review or fix.
"""
import contextlib, threading

from pr_loop import config, queue as q, scope

LANES = "review", "fix"
SCOPE = "scope", None


def name(lane, repo):
    return f"{lane}:{repo}" if repo else lane


def wanted(cfg, listing):
    """{(lane, repo): workers}: `repo` None for the shared pools, else one pool per project with that lane on."""
    if not cfg["lanes"]["separate"]:
        return {(lane, None): cfg[lane]["workers"] for lane in LANES}
    return {(lane, p["repo"]): config.effective(cfg, p["repo"])[lane]["workers"]
            for p in listing for lane in LANES if p[lane]}


def spawn(lane, pool):
    if lane == "scope":
        return q.worker(pool, True, scope.run, lock=lambda repo, n: contextlib.nullcontext(True))
    return q.worker(pool, True, q.reviewer(None, False) if lane == "review" else q.fix)


class Pools:
    def __init__(self):
        self.cond, self.held, self.pools, self.paused = threading.Condition(), set(), {}, False

    def apply(self, cfg, listing):
        """Builds the pool set `cfg` asks for, live, and returns the workers it started."""
        want, started = wanted(cfg, listing), []
        with self.cond:
            for key in self.pools.keys() - want.keys() - {SCOPE}:
                gone = self.pools.pop(key)
                gone.refill([])
                gone.resize(0, list)
            for (lane, repo), workers in want.items():
                pool = self.pools.setdefault((lane, repo), q.Pending(cond=self.cond, held=self.held))
                pool.paused = self.paused
                started += pool.resize(workers, lambda: spawn(lane, pool))
            lens = self.pools.setdefault(SCOPE, q.Pending(cond=self.cond))
            lens.paused = self.paused
            started += lens.resize(cfg["scope"]["workers"] * cfg["scope"]["enabled"], lambda: spawn("scope", lens))
        return started

    def refill(self, lane, prs):
        """Routes each PR to the pool of its lane that serves its repo."""
        with self.cond:
            for pool, repo in self.of(lane):
                pool.refill([pr for pr in prs if repo in (None, pr["repo"])])

    def of(self, lane):
        with self.cond:
            return [(pool, repo) for (l, repo), pool in self.pools.items() if l == lane]

    def pause(self, on):
        with self.cond:
            self.paused = on
            for pool in self.pools.values():
                pool.pause(on)

    def idle(self):
        return any(pool.idle() for pool, _ in self.of("review"))

    def sizes(self):
        with self.cond:
            return {name(*key): pool.workers for key, pool in self.pools.items()}
