"""The runtime behind `python3 -m pr_wizard.api --fake`: the fixtures of tests/fixtures/api/v1 as a stateful, in-memory
daemon (api.md §7). Writes and actions change the snapshot as the daemon would and wake the long-polls. Nothing touches disk.

Knobs, as env vars because the CLI of `pr_wizard.api` has none:
  PRW_FAKE_SPEED=<s>   seconds one review or fix takes (default 3, 0 = instant)
  PRW_FAKE_EMPTY=1     start with an empty queue (the history view)
"""
import copy, hashlib, json, os, secrets, threading, time
from datetime import datetime

from pr_wizard import api, config, db, names

FIXTURES = os.path.join(names.ROOT, "tests", "fixtures", "api", "v1")
GROUPS = ("active", "queued", "ready", "idle")
KEEP_EVENTS, ZERO = 1000, dict.fromkeys(("critical", "high", "medium", "low"), 0)


class Runtime:
    def __init__(self, fixtures=FIXTURES, speed=None, epoch=None, empty=None):
        self.fixtures, self.changes, self.lock = fixtures, api.Changes(), threading.RLock()
        self.speed = float(os.environ.get("PRW_FAKE_SPEED", 3)) if speed is None else speed
        self.snap, self.info_doc = self.read("queue"), self.read("info")
        self.page = self.read("config")
        self.cfg = self.page.pop("config")
        self.log, self.hist, self.version = self.read("events")["events"], self.read("history")["entries"], 0
        self.epoch = epoch or "k" + secrets.token_hex(3)
        self.bumps = [i["key"] for i in self.snap["items"] if i["bumped"]]
        if os.environ.get("PRW_FAKE_EMPTY") if empty is None else empty:
            self.snap["items"] = []
            self.counts()

    def read(self, name):
        with open(os.path.join(self.fixtures, f"{name}.json"), encoding="utf-8") as fh:
            return json.load(fh)

    # ---------------------------------------------------------------- reads

    def get(self, doc):
        with self.lock:
            return copy.deepcopy(doc)

    def info(self):
        return self.get(self.info_doc)

    def snapshot(self):
        return self.get(self.snap)

    def config(self):
        with self.lock:
            effective = {p["repo"]: {"root": p["checkout"] and p["checkout"]["path"], **config.effective(self.cfg, p["repo"])}
                         for p in self.snap["projects"] if p["repo"] in self.page["effective"]}
            return copy.deepcopy({**self.page, "rev": config.rev(self.cfg), "config": self.cfg, "effective": effective})

    def events(self, since):
        with self.lock:
            head, oldest = self.log[-1]["seq"] if self.log else 0, self.log[0]["seq"] if self.log else 1
            cursor, (epoch, _, n) = f"{self.epoch}.{head}", (since or "").partition(".")
            if since is None:
                return {"cursor": cursor, "reset": False, "events": []}
            reset = epoch != self.epoch or not n.isdigit() or int(n) < oldest - 1
            return {"cursor": cursor, "reset": reset, "events": self.get([e for e in self.log if reset or e["seq"] > int(n)])}

    def history(self, repo, limit):
        with self.lock:
            return {"entries": self.get([h for h in self.hist if repo in (None, h["repo"])][:limit])}

    # ---------------------------------------------------------------- the snapshot

    def publish(self):
        """Settles ranks, counts, pools, projects and `rev`, then wakes the long-polls. Call with the lock held."""
        snap, keys = self.snap, self.bumps
        first = lambda i: keys.index(i["key"]) if i["key"] in keys else len(keys)
        snap["items"].sort(key=lambda i: (GROUPS.index(i["group"]), first(i) * (i["group"] == "queued")))
        for rank, i in enumerate((i for i in snap["items"] if i["group"] == "queued"), 1):
            i["rank"] = rank
        for i in snap["items"]:
            i["bumped"] = i["key"] in keys
            i["rank"] = i["rank"] if i["group"] == "queued" else None
        for p in snap["projects"]:
            if p["checkout"]:
                on = config.effective(self.cfg, p["repo"])
                p["review"], p["fix"] = on["review"]["enabled"], on["fix"]["enabled"]
                p["status"] = "active" if p["review"] or p["fix"] else "off"
        self.counts()
        snap["lanes"] = self.lanes()
        snap["generated_at"] = db.now()
        self.version += 1
        body = {k: v for k, v in snap.items() if k not in ("rev", "generated_at")}
        snap["rev"] = hashlib.sha1(f"{self.version}{json.dumps(body, sort_keys=True)}".encode()).hexdigest()[:16]
        self.info_doc.update(paused=snap["paused"], projects=snap["projects"], lanes=snap["lanes"], refresh=snap["refresh"])
        self.info_doc["config"]["rev"] = config.rev(self.cfg)
        self.changes.touch()

    def counts(self):
        self.snap["counts"] = {g: sum(i["group"] == g for i in self.snap["items"]) for g in GROUPS}

    def lanes(self):
        items, separate = self.snap["items"], self.cfg["lanes"]["separate"]
        busy = lambda lane, repo: sum(bool(i["active"]) and i["active"]["lane"] == lane and repo in (None, i["repo"]) for i in items)
        pending = lambda lane, repo: sum(repo in (None, i["repo"]) and (
            i["group"] == "queued" if lane == "review" else i["fix_queued"] and not i["active"]) for i in items)

        def pool(lane, repo, workers):
            return {"id": f"{lane}:{repo}" if repo else lane, "lane": lane, "repo": repo, "workers": workers,
                    "busy": busy(lane, repo), "pending": pending(lane, repo)}
        if not separate:
            return {"separate": False, "pools": [pool(lane, None, self.cfg[lane]["workers"]) for lane in ("review", "fix")]}
        return {"separate": True, "pools": [pool(lane, p["repo"], config.effective(self.cfg, p["repo"])[lane]["workers"])
                                           for p in self.snap["projects"] if p["checkout"] for lane in ("review", "fix")
                                           if p[lane]]}

    # ---------------------------------------------------------------- writes and actions

    def save_config(self, doc):
        with self.lock:
            self.cfg = copy.deepcopy(doc)
            self.publish()
        return self.config()

    def refetch(self):
        with self.lock:
            now = db.now()
            self.snap["fetched_at"] = self.snap["refresh"]["last_at"] = now
            if item := next((i for i in self.snap["items"] if i["group"] == "ready" and not i["mine"]), None):
                self.emit("ready_for_approval", item, (item["review"] or {}).get("verdict") or "quality-only")
            self.publish()

    def emit(self, kind, item, verdict):
        seq = self.log[-1]["seq"] + 1 if self.log else 1
        self.log = (self.log + [{
            "id": f"{kind}:{item['key']}@{item['head'][:12]}", "seq": seq, "type": kind, "key": item["key"],
            "repo": item["repo"], "number": item["number"], "title": item["title"], "url": item["url"],
            "author": item["author"], "head": item["head"], "verdict": verdict, "at": db.now()}])[-KEEP_EVENTS:]

    def bump(self, prs, only_queued):
        with self.lock:
            items, repos = {i["key"]: i for i in self.snap["items"]}, {p["repo"] for p in self.snap["projects"]}
            why = [self.unbumpable(repo, items.get(f"{repo}#{n}"), repos) if only_queued or repo not in repos else None
                   for repo, n in prs]
            go = [f"{repo}#{n}" for (repo, n), reason in zip(prs, why) if reason is None]
            for key in go:
                if (item := items.get(key)) and item["group"] == "idle":
                    item.update(group="queued", status="queued", detail="bumped")
            self.bumps = go + [k for k in self.bumps if k not in go]
            self.publish()
            return {"next": self.get(self.bumps), "results": [{"key": f"{repo}#{n}", "bumped": reason is None, "reason": reason}
                                                              for (repo, n), reason in zip(prs, why)]}

    def unbumpable(self, repo, item, repos):
        if repo not in repos:
            return "unknown-repo"
        if not item:
            return "not-in-queue"
        if item["active"]:
            return "active"
        if not self.lane_on(item, "review"):
            return "review-lane-off"
        return None if item["group"] == "queued" or item["status"] in ("held", "new") else "nothing-new"

    def lane_on(self, item, lane):
        project = next(p for p in self.snap["projects"] if p["repo"] == item["repo"])
        return project[lane] and f"no-auto-{lane}" not in item["labels"]

    def target(self, repo, n):
        if repo not in {p["repo"] for p in self.snap["projects"]}:
            raise api.Problem(404, "unknown_repo", f"{repo} is not a known project")
        return next((i for i in self.snap["items"] if i["key"] == f"{repo}#{n}"), None)

    def hold(self, item):
        if item["active"]:
            raise api.Problem(409, "busy", f"a live run already holds {item['key']}")

    def review(self, repo, n):
        with self.lock:
            item = self.target(repo, n)
            project = next(p for p in self.snap["projects"] if p["repo"] == repo)
            if not project["checkout"]:
                raise api.Problem(409, "no_checkout", f"{repo} has no local checkout, set projects[{repo}].root")
            if not config.effective(self.cfg, repo)["review"]["enabled"]:
                raise api.Problem(409, "review_lane_off", f"the review lane of {repo} is off")
            if item is None:
                return
            self.hold(item)
            if item["group"] == "ready" and not item["mine"]:
                self.emit("ready_withdrawn", item, None)
            ids = [r for r in config.effective(self.cfg, repo)["review"]["reviewers"] if r["enabled"]]
            now = db.now()
            item.update(group="active", status="reviewing", detail=f"since {now[11:19]}", active={
                "lane": "review", "since": now,
                "reviewers": [{"id": r["id"], "state": "running", "attempt": 1, "since": now} for r in ids]})
            self.publish()
        self.run([lambda r=r: r.update(state="clean", since=db.now()) for r in item["active"]["reviewers"]]
                 + [lambda: self.reviewed(item, ids)])

    def reviewed(self, item, reviewers):
        now, old = db.now(), item["review"] or {}
        rounds = old.get("rounds") or 1
        item["review"] = {"sha": item["head"], "current": True, "status": "clean", "verdict": "clean", "note": "",
                          "rounds": rounds, "hold": item["mine"], "at": now}
        item["findings"] = {"head": item["head"], "current": True, "round": rounds, "at_floor": 0,
                            "conventions": (item["findings"] or {}).get("conventions", []), "top": [], "reviewers": [
                                {"id": r["id"], "label": r["label"], "result": "clean", "engine": r["engine"],
                                 "counts": dict(ZERO), "at_floor": 0, "top": [], "url": None, "at": now}
                                for r in reviewers]}
        item["active"] = None
        if item["mine"]:
            item.update(group="idle", status="clean", detail=f"--next {item['number']} to review")
        else:
            item.update(group="ready", status="ready", detail=now.replace("T", " ")[:19])
            self.emit("ready_for_approval", item, "clean")
        self.upsert(item, "clean" if item["mine"] else "ready")

    def upsert(self, item, outcome):
        old = next((h for h in self.hist if h["key"] == item["key"]), None)
        entry = {"key": item["key"], "repo": item["repo"], "number": item["number"], "title": item["title"],
                 "url": item["url"], "author": item["author"], "mine": item["mine"], "state": "settled",
                 "outcome": outcome, "rounds": item["review"]["rounds"], "fixes_pushed": (old or {}).get("fixes_pushed", 0),
                 "head": item["head"], "first_at": (old or {}).get("first_at") or db.now(), "at": db.now(),
                 "closed_at": None, "findings": item["findings"]}
        self.hist = [entry] + [h for h in self.hist if h["key"] != item["key"]]

    def fix(self, repo, n):
        with self.lock:
            item = self.target(repo, n)
            if item is None:
                raise api.Problem(404, "not_in_queue", f"{repo}#{n} is not in the last queue fetch")
            if not item["mine"]:
                raise api.Problem(409, "not_mine", f"{item['key']} is not my PR")
            if "no-auto-fix" in item["labels"]:
                raise api.Problem(409, "no_auto_fix", f"{item['key']} is labeled no-auto-fix")
            if not self.lane_on(item, "fix"):
                raise api.Problem(409, "fix_lane_off", f"the fix lane of {repo} is off")
            self.hold(item)
            before, now = {k: item[k] for k in ("group", "status", "detail")}, db.now()
            item.update(group="active", status="fixing", detail=f"since {now[11:19]}",
                        active={"lane": "fix", "since": now, "reviewers": None})
            self.publish()
        self.run([lambda: self.fixed(item, before)])

    def fixed(self, item, before):
        item.update(before, active=None, fix_queued=False, fix={
            "sha": item["head"], "current": True, "status": "nothing-to-fix", "note": "", "errors": 0, "parked": False,
            "at": db.now()})

    def pause(self, on):
        with self.lock:
            self.snap["paused"] = on
            self.publish()
        return on

    def run(self, steps):
        """Applies `steps` one after another, `speed` seconds in all, off the request thread. Instant at speed 0."""
        def go():
            for step in steps:
                if self.speed:
                    time.sleep(self.speed / len(steps))
                with self.lock:
                    step()
                    self.publish()
        threading.Thread(target=go, daemon=True).start() if self.speed else go()


def history(rt, query, body):
    limit = query.get("limit", ["20"])[-1]
    if not (limit.isdigit() and 1 <= int(limit) <= 100):
        raise api.bad("limit must be an integer from 1 to 100")
    return rt.history(query.get("repo", [None])[-1], int(limit))


api.ROUTES.setdefault("/v1/history", {"GET": history})
