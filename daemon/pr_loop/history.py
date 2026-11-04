"""History (api.md §3.13): the PRs PR Loop worked on, for the empty queue window.

  review / fix result ──remember──▶ history row, in the result's transaction
  PR leaves the fetch ──settle────▶ one batched pullRequest(number:) query ──▶ state merged | closed, override dropped
  daemon start, once ─▶ seed ─────▶ rows from the reviews and fixes the db already holds
  GET /v1/history ────▶ entries ──▶ rows, minus the open PRs the queue still works, plus the findings digest

`seed` and `entries` import `snapshot` on call: it imports `queue`, which imports this module.
"""
import json
import time
from datetime import datetime, timedelta

from pr_loop import db

READY = ("clean", "quality-only")
WORKED = ("posted", "clean", "failed", "needs-human", "too-big")
STATES = {"open": "settled", "merged": "merged", "closed": "closed"}
LOOKUP, RECHECK = 20, 1800
FIELDS = "state title url closedAt viewerDidAuthor headRefOid author { login ... on User { name } }"
LOOKED = {}


def url(repo, n):
    return f"https://github.com/{repo}/pull/{n}"


def author(pr):
    """The login, and the display name when the author is a user who set one."""
    who = pr["author"] or {}
    return {"author": who.get("login", "ghost"), "author_name": who.get("name") or None}


def outcome(status, verdict, mine):
    """`ready` for a colleague's PR the reviewers cleared, else the verdict, else the status."""
    return "ready" if verdict in READY and not mine else verdict or status


def rounds(repo, n):
    """The highest round the reviewers posted at the latest head."""
    return max((r["round"] or 0 for r in db.reviewer_results(repo, n).values()), default=0)


def remember(pr, result, pushed=0):
    """Upserts the PR's row after a review or fix result. Call it inside the transaction that records the result."""
    repo, n = pr["repo"], pr["number"]
    found = rounds(repo, n)
    db.upsert_history(repo, n, pushed=pushed, title=pr["title"], url=url(repo, n), mine=pr["viewerDidAuthor"],
                      **author(pr), outcome=result, head=pr["headRefOid"],
                      state="open", closed_at=None, **({"rounds": found} if found else {}))


def lookup(graphql, pairs):
    """({(repo, number): PR node}, points spent) in one query per LOOKUP PRs: `pullRequest(number:)` aliases, no search."""
    found, cost = {}, 0
    for i in range(0, len(pairs), LOOKUP):
        repos = {}
        for repo, n in pairs[i:i + LOOKUP]:
            repos.setdefault(repo, []).append(n)
        body = " ".join(
            f"r{j}: repository(owner: {json.dumps(repo.split('/')[0])}, name: {json.dumps(repo.split('/')[1])}) {{ "
            + " ".join(f"p{n}: pullRequest(number: {n}) {{ {FIELDS} }}" for n in ns) + " }"
            for j, (repo, ns) in enumerate(repos.items()))
        data = graphql(f"query {{ rateLimit {{ cost }} {body} }}", {})
        found |= {(repo, n): data[f"r{j}"][f"p{n}"] for j, (repo, ns) in enumerate(repos.items()) for n in ns}
        cost += data["rateLimit"]["cost"]
    return found, cost


def settle(graphql, prs, say):
    """Marks the open entries whose PR left the fetch `merged` or `closed`, and drops those PRs' overrides (api.md
    §4.10), pauses and done marks, also of PRs with no entry. A PR the lookup finds open stays out of the next lookups for RECHECK seconds."""
    inside, now = {(p["repo"], p["number"]) for p in prs}, time.monotonic()
    entries = [(r["repo"], r["number"]) for r in db.history(db.HISTORY_KEEP) if r["state"] == "open"]
    gone = [k for k in dict.fromkeys(entries + list(db.pr_overrides()) + list(db.paused_prs())
                                       + list(db.done_prs()))
            if k not in inside and now - LOOKED.get(k, -RECHECK) >= RECHECK]
    LOOKED.update(dict.fromkeys(gone, now))
    if not gone:
        return
    found, cost = lookup(graphql, gone)
    with db.tx():
        for (repo, n), node in found.items():
            if node["state"] != "OPEN":
                (repo, n) in entries and db.upsert_history(repo, n, state=node["state"].lower(), closed_at=db.now(),
                                                           author_name=author(node)["author_name"])
                db.drop_pr_override(repo, n)
                db.pause_pr(repo, n, False)
                db.mark_done(repo, n, None)
    say(f"history: {len(gone)} PR(s) left the queue, {sum(n['state'] != 'OPEN' for n in found.values())} merged or closed, "
        f"lookup cost {cost} points")


def stored():
    """{(repo, number): [(at, status, verdict, sha, rounds, pushed)]} of the stored review and fix rows inside the
    retention window, newest first."""
    cutoff = datetime.now().astimezone() - timedelta(days=db.DAYS)
    rows = {}
    for repo in db.result_repos():
        for n, r in db.reviews(repo).items():
            if r["status"] in WORKED or r["verdict"]:
                rows.setdefault((repo, n), []).append((r["at"], r["status"], r["verdict"], r["sha"], r["rounds"], 0))
        for n, f in db.fixes(repo).items():
            rows.setdefault((repo, n), []).append((f["at"], f["status"], None, f["sha"], 0, int(f["status"] == "pushed")))
    return {k: sorted(v, reverse=True) for k, v in rows.items()
            if datetime.fromisoformat(max(v)[0]).astimezone() >= cutoff}


def seed(graphql, prs, say):
    """Once: a row per PR the db holds a review or fix result of, so the empty state is not blank on day one.
    Title and author are not stored: the fetch has the open PRs, one lookup the rest. The db keeps only the last
    pass of each lane, so `fixes_pushed` is 1 at most."""
    if db.meta_get("history_seeded"):
        return
    from pr_loop.snapshot import iso
    known = {(r["repo"], r["number"]) for r in db.history(db.HISTORY_KEEP)}
    rows = {k: v for k, v in stored().items() if k not in known}
    live = {(p["repo"], p["number"]): p for p in prs}
    found, cost = lookup(graphql, [k for k in rows if k not in live])
    with db.tx():
        for (repo, n), passes in rows.items():
            node = live.get((repo, n)) or found[repo, n]
            last, mine = passes[0], node["viewerDidAuthor"]
            closed = node["state"] != "OPEN"
            db.upsert_history(
                repo, n, title=node["title"], url=url(repo, n), mine=mine, **author(node),
                outcome=outcome(last[1], last[2], mine), rounds=max(rounds(repo, n), *(p[4] for p in passes)),
                fixes_pushed=max(p[5] for p in passes), head=last[3], first_at=iso(passes[-1][0]),
                at=iso(last[0]), state=node["state"].lower() if closed else "open",
                closed_at=iso(node["closedAt"]) if closed else None)
        db.meta_set("history_seeded", 1)
    say(f"history: seeded {len(rows)} PR(s) from the stored results, lookup cost {cost} points")


def entries(rows, busy, approved, todo, cfg, limit):
    """The API entries: the newest `limit` rows that are not open PRs the queue still works. `approved`, `busy` and
    `todo` are sets of PR keys; my standing approval beats the stored outcome, and a PR off the to-do list is done."""
    from pr_loop.snapshot import findings
    shown = [r for r in rows if r["state"] != "open" or r["key"] not in busy][:limit]
    return [dict(r, state=STATES[r["state"]], outcome="approved" if r["key"] in approved else r["outcome"],
                 done=r["key"] not in todo,
                 findings=findings(r["repo"], db.review(r["repo"], r["number"]),
                                            db.reviewer_results(r["repo"], r["number"]), r["head"], cfg))
            for r in shown]
