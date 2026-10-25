"""The queue snapshot of api.md §3.2: `read()` takes the db rows, `build()` turns them and the fetched PRs into the
API JSON, `render()` prints it as the `-l` lines."""
import hashlib, json
from datetime import datetime

from pr_wizard import config, db, queue as q
from pr_wizard.names import tag

GROUPS = {0: "active", 1: "queued", 3: "ready", 4: "idle"}
MARKS = {"active": "▶", "ready": "✓"}
SEVERITIES = ("critical", "high", "medium", "low")
EMPTY = {"counts": dict.fromkeys(SEVERITIES, 0), "at_floor": 0, "top": []}


def read():
    """The db rows behind a snapshot. `reviews` and `fixes` keep the str keys the gate functions take."""
    repos = {repo: {"reviews": q.load(repo), "fixes": q.load(repo, q.FIXES), "next": db.next_list(repo)}
             for repo in q.projects()}
    for repo, rows in repos.items():
        rows["results"] = {int(n): db.reviewer_results(repo, n) for n in rows["reviews"]}
    return {"repos": repos, "runs": db.live_runs(), "config": q.cfg(), "roots": q.projects()}


def iso(at):
    return datetime.fromisoformat(at).astimezone().isoformat(timespec="seconds")


def findings(repo, seen, results, head, cfg):
    """The digest of the last reviewed head. A reviewer that failed or hit the limit there stores no row: the
    review status names its result."""
    if not results:
        return None
    sha = next(iter(results.values()))["sha"]
    known = {r["id"]: r for r in config.effective(cfg, repo)["review"]["reviewers"]}
    derived = seen.get("status") if seen.get("sha") == sha and seen.get("status") in ("failed", "limited") else None
    reviewers = []
    for rid in known:
        if row := results.get(rid):
            reviewers.append({"id": rid, "label": known[rid]["label"], "result": row["result"],
                              "engine": row["engine"] or known[rid]["engine"], **(row["digest"] or EMPTY),
                              "url": row["url"], "at": iso(row["at"])})
        elif derived:
            reviewers.append({"id": rid, "label": known[rid]["label"], "result": derived,
                              "engine": known[rid]["engine"], **EMPTY, "url": None, "at": iso(seen["at"])})
    ranked = sorted((dict(t, reviewer=r["id"], url=r["url"]) for r in reviewers for t in r["top"]),
                    key=lambda t: SEVERITIES.index(t["severity"]))
    return {"head": sha, "current": sha == head, "round": max(r["round"] for r in results.values()),
            "at_floor": sum(r["at_floor"] for r in reviewers),
            "conventions": next((r["conventions"] for r in results.values() if r["conventions"]), []),
            "reviewers": reviewers, "top": ranked[:3]}


def entry(pr, rows, runs, cfg, first):
    repo, n, head = pr["repo"], pr["number"], pr["headRefOid"]
    seen, fixed = rows["reviews"].get(str(n), {}), rows["fixes"].get(str(n), {})
    now = {k: f"{r['lane']} {r['since'][11:19]}" for (r_repo, k), r in runs.items() if r_repo == repo}
    group, status, detail = q.row(pr, seen, now, first, fixed)
    run = runs.get((repo, n))
    return {
        "key": f"{repo}#{n}", "repo": repo, "number": n, "title": pr["title"], "url": q.url(repo, n),
        "author": (pr["author"] or {}).get("login", "ghost"), "mine": pr["viewerDidAuthor"], "draft": pr["isDraft"],
        "labels": [l["name"] for l in pr["labels"]["nodes"]], "head": head, "base": pr["baseRefName"],
        "additions": pr["additions"], "deletions": pr["deletions"],
        "pushed_at": iso(pr["commits"]["nodes"][0]["commit"]["committedDate"]), "updated_at": iso(pr["updatedAt"]),
        "requested": pr["requested"], "bumped": n in first, "group": GROUPS[group], "rank": None,
        "status": status, "detail": detail,
        "active": run and {"lane": run["lane"], "since": run["since"],
                           "reviewers": run["reviewers"] if run["lane"] == "review" else None},
        "review": {k: v for k, v in seen.items() if k != "files"} | {"current": seen["sha"] == head, "at": iso(seen["at"])}
        if seen else None,
        "findings": findings(repo, seen, rows["results"].get(n), head, cfg),
        "fix": {k: v for k, v in fixed.items() if k not in ("key", "gate")}
        | {"current": fixed["sha"] == head, "parked": fixed["errors"] >= config.effective(cfg, repo)["fix"]["max_errors"], "at": iso(fixed["at"])}
        if fixed else None,
        "fix_queued": q.fixing(pr, rows["reviews"], rows["fixes"]), "override": [],
        "fixable": q.fixable(pr, rows["reviews"], rows["fixes"]),
    }


def build(prs, state, runtime):
    """Pure: the fetched PRs, `read()` rows and the runtime {generated_at, fetched_at, paused, refresh} as the §3.2
    snapshot."""
    repos, runs, cfg, roots = state["repos"], state["runs"], state["config"], state["roots"]
    on = {repo: config.effective(cfg, repo) for repo in roots}
    first = {repo: rows["next"] for repo, rows in repos.items()}
    active = {repo: [n for r, n in runs if r == repo] for repo in repos}
    rows = [(entry(pr, repos[pr["repo"]], runs, cfg, first[pr["repo"]]), pr) for pr in prs]
    rows = sorted(((i, pr) for i, pr in rows if i["active"] or not q.approved(pr)),
                  key=lambda r: (list(GROUPS.values()).index(r[0]["group"]), q.priority(r[1], first),
                                 r[1]["number"] < max(active[r[1]["repo"]], default=0), r[1]["number"], r[1]["repo"]))
    items = [i for i, _ in rows]
    for rank, i in enumerate((i for i in items if i["group"] == "queued"), 1):
        i["rank"] = rank
    fixable = sum(i.pop("fixable") and not i["active"] for i in items)
    busy = lambda lane: sum(bool(i["active"]) and i["active"]["lane"] == lane for i in items)
    snap = {
        "fetched_at": runtime["fetched_at"], "paused": runtime["paused"],
        "lanes": {"separate": False, "pools": [
            {"id": "review", "lane": "review", "repo": None, "workers": cfg["review"]["workers"], "busy": busy("review"),
             "pending": sum(i["group"] == "queued" for i in items)},
            {"id": "fix", "lane": "fix", "repo": None, "workers": cfg["fix"]["workers"], "busy": busy("fix"),
             "pending": fixable}]},
        "projects": [{"repo": repo, "status": "active", "available": True, "review": on[repo]["review"]["enabled"],
                      "fix": on[repo]["fix"]["enabled"], "checkout": {"path": path, "source": "config"},
                      "prs": sum(pr["repo"] == repo for pr in prs), "error": None, "conventions": None, "gates": []}
                     for repo, path in roots.items()],
        "refresh": runtime["refresh"],
        "counts": {g: sum(i["group"] == g for i in items) for g in GROUPS.values()},
        "items": items,
    }
    rev = hashlib.sha1(json.dumps(snap, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return {"rev": rev, "generated_at": runtime["generated_at"], **snap}


def render(snap, tty=False):
    """The `-l` lines: ▶ in work, 1..n review order, ✓ ready, then the rest."""
    lines = []
    for i in snap["items"]:
        mark = str(i["rank"]) if i["rank"] else MARKS.get(i["group"], "")
        name = f"{tag(i['repo'])[1:]}#{i['number']}"
        link = f"\033]8;;{i['url']}\033\\{name}\033]8;;\033\\" if tty else name
        lines.append(f"{mark:>2}  {link}  {i['status']:<9}  {i['detail']:<20}  {'[draft] ' * i['draft']}{i['title']}")
    return "".join(f"{line}\n" for line in lines)
