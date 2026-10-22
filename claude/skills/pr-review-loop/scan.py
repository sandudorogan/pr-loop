#!/usr/bin/env python3
"""Review-loop scanner.

Usage:
  scan.py scan            # print actionable work as JSON
  scan.py mark <PR>       # record current feedback/checks as handled, attempts += 1
  scan.py status          # print state summary (local state only, no API calls)
  scan.py report [PR...]  # print the evidence sweep for a PR (defaults to all)

Reads its PR list from prs.json (a {"<pr>": "<head-branch>"} map) next to this
script, tracks per-PR handled feedback in state.json, and reports the PRs that
have new, unhandled feedback or failing CI.

Treats as actionable: new bot/human reviews, new inline review comments, new
issue comments, and failing CI checks (tracked per name@head-sha). Skips the PR
owner and boilerplate bots -- except for our own review agents, which post under
the owner's token and mark themselves with `<!-- agent-review: ... -->` (a notes-only
review also carries `<!-- agent-review-fyi -->` and stays skipped). Caps work
at MAX_ATTEMPTS, then flips a PR to needs-human so the loop surfaces it instead of
churning on it forever.

Inline comments come from the GraphQL reviewThreads connection rather than the
REST comments list, so each one carries its thread's resolved/outdated state.
Resolved threads are never actionable; outdated ones are, but flagged, since an
outdated thread means the reviewer saw a stale head.

On my own PRs, reviews and review threads belong to the review queue's fix lane
(pr_fix.py), so only issue comments and failing CI are actionable there.
"""
import json, subprocess, sys, os

REPO = "iprally/iprally"
DIR = os.path.dirname(os.path.abspath(__file__))
PRS = os.path.join(DIR, "prs.json")
STATE = os.path.join(DIR, "state.json")
REPO_ROOT = os.environ.get("IPR_REPO_ROOT", os.path.expanduser("~/workdir/iprally"))
WT_BASE = os.path.join(REPO_ROOT, ".claude", "worktrees")
BOILERPLATE_BOTS = {"linear-code[bot]", "pvbctl[bot]"}
AGENT_MARKER = "<!-- agent-review:"
FYI_MARKER = "<!-- agent-review-fyi -->"
MAX_ATTEMPTS = 4

_me = None


def me():
    global _me
    if _me is None:
        out = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                             capture_output=True, text=True, timeout=60)
        _me = out.stdout.strip()
    return _me


def norm_login(login):
    """REST says `cursor[bot]`, GraphQL says `cursor`. Compare on one form."""
    return (login or "").removesuffix("[bot]")


def exclude():
    return {norm_login(x) for x in BOILERPLATE_BOTS | {me()}}


def suppressed(rec, skip):
    """Our review agents post under the owner's token, so the owner filter would
    swallow them. The marker they stamp on every review and inline comment is what
    lets them back through, unless the review is notes only and leaves nothing to fix."""
    body = rec.get("body") or ""
    if AGENT_MARKER in body:
        return FYI_MARKER in body
    return norm_login(rec.get("user", "")) in skip


def worktree_for(branch):
    return os.path.join(WT_BASE, branch.replace("/", "+"))


def gh_json(args):
    try:
        out = subprocess.run(["gh", "api"] + args, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return []
        return json.loads(out.stdout or "[]")
    except Exception:
        return []


def pr_view(pr, fields):
    try:
        out = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", REPO, "--json", fields],
            capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return {}
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def pr_state(pr):
    return pr_view(pr, "state,headRefOid,mergedAt,closed,author")


def failing_checks(pr, sha):
    runs = gh_json([f"repos/{REPO}/commits/{sha}/check-runs", "--paginate", "--jq", ".check_runs"])
    fails = []
    if isinstance(runs, list):
        for r in runs:
            if r.get("conclusion") in ("failure", "timed_out", "action_required"):
                fails.append({"sig": f"{r.get('name')}@{sha}", "name": r.get("name"),
                              "url": r.get("details_url")})
    return fails


THREADS_QUERY = (
    "query($owner:String!,$repo:String!,$number:Int!,$cursor:String){"
    "repository(owner:$owner,name:$repo){pullRequest(number:$number){"
    "reviewThreads(first:50,after:$cursor){"
    "pageInfo{hasNextPage endCursor}"
    "nodes{id isResolved isOutdated path line "
    "comments(first:50){nodes{databaseId author{login} body}}}}}}}"
)


def review_threads(pr):
    owner, name = REPO.split("/")
    threads, cursor = [], None
    while True:
        args = ["gh", "api", "graphql", "-f", f"query={THREADS_QUERY}",
                "-f", f"owner={owner}", "-f", f"repo={name}", "-F", f"number={pr}"]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=60)
            if out.returncode != 0:
                return threads
            page = json.loads(out.stdout or "{}")
        except Exception:
            return threads
        pull = ((page.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
        conn = pull.get("reviewThreads") or {}
        threads.extend(conn.get("nodes") or [])
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return threads
        cursor = info.get("endCursor")


def flatten_threads(threads):
    """One record per inline comment, carrying its thread's state."""
    out = []
    for t in threads:
        for c in ((t.get("comments") or {}).get("nodes") or []):
            out.append({"id": c.get("databaseId"),
                        "user": (c.get("author") or {}).get("login", ""),
                        "path": t.get("path"), "line": t.get("line"),
                        "body": c.get("body"),
                        "thread_id": t.get("id"),
                        "resolved": bool(t.get("isResolved")),
                        "outdated": bool(t.get("isOutdated"))})
    return out


def gather(pr):
    reviews = gh_json([f"repos/{REPO}/pulls/{pr}/reviews", "--jq",
                       "[.[] | {id, user: .user.login, state, body}]"])
    threads = review_threads(pr)
    issues = gh_json([f"repos/{REPO}/issues/{pr}/comments", "--jq",
                      "[.[] | {id, user: .user.login, body}]"])
    return reviews, threads, issues


def actionable(pr, st):
    skip = exclude()
    reviews, threads, issues = gather(pr)
    inline = flatten_threads(threads)
    new_reviews = [r for r in reviews if r["id"] not in st["seen_review_ids"]
                   and not suppressed(r, skip)
                   and (r.get("body") or r.get("state") == "CHANGES_REQUESTED")]
    new_inline = [c for c in inline if c["id"] not in st["seen_inline_ids"]
                  and not suppressed(c, skip) and not c["resolved"]]
    new_issue = [c for c in issues if c["id"] not in st["seen_issue_ids"]
                 and not suppressed(c, skip)]
    meta = pr_state(pr)
    if norm_login(meta.get("author", {}).get("login")) == norm_login(me()):
        new_reviews, new_inline = [], []
    meta["unresolved_threads"] = sum(1 for t in threads if not t.get("isResolved"))
    sha = meta.get("headRefOid", "")
    fails = [f for f in failing_checks(pr, sha) if f["sig"] not in st["handled_check_runs"]]
    return meta, new_reviews, new_inline, new_issue, fails, (reviews, inline, issues, sha)


def main():
    prs = load(PRS, {})
    state = load(STATE, {})
    for pr in prs:
        state.setdefault(pr, {"seen_review_ids": [], "seen_inline_ids": [],
                              "seen_issue_ids": [], "handled_check_runs": [],
                              "attempts": 0, "status": "active"})
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        work = []
        for pr, branch in prs.items():
            st = state[pr]
            if st["status"] in ("merged", "closed", "needs-human"):
                continue
            meta, nr, ni, nis, fails, _ = actionable(pr, st)
            if meta.get("mergedAt") or meta.get("state") == "MERGED":
                st["status"] = "merged"; continue
            if meta.get("closed") or meta.get("state") == "CLOSED":
                st["status"] = "closed"; continue
            if st["attempts"] >= MAX_ATTEMPTS and (nr or ni or nis or fails):
                st["status"] = "needs-human"; continue
            if nr or ni or nis or fails:
                work.append({
                    "pr": pr, "branch": branch,
                    "worktree": worktree_for(branch),
                    "attempts": st["attempts"],
                    "head_sha": meta.get("headRefOid", ""),
                    "unresolved_threads": meta["unresolved_threads"],
                    "new_reviews": nr, "new_inline": ni,
                    "new_issue_comments": nis, "failing_checks": fails,
                })
        save(STATE, state)
        print(json.dumps({"work": work, "count": len(work)}, indent=2))

    elif cmd == "mark":
        pr = sys.argv[2]
        st = state[pr]
        reviews, inline, issues, sha = actionable(pr, st)[5]
        st["seen_review_ids"] = list({r["id"] for r in reviews} | set(st["seen_review_ids"]))
        st["seen_inline_ids"] = list({c["id"] for c in inline} | set(st["seen_inline_ids"]))
        st["seen_issue_ids"] = list({c["id"] for c in issues} | set(st["seen_issue_ids"]))
        for f in failing_checks(pr, sha):
            if f["sig"] not in st["handled_check_runs"]:
                st["handled_check_runs"].append(f["sig"])
        st["attempts"] += 1
        save(STATE, state)
        print(f"marked {pr}: attempts={st['attempts']}")

    elif cmd == "status":
        for pr, st in state.items():
            print(f"PR {pr} ({prs.get(pr,'?')}): status={st['status']} attempts={st['attempts']}")

    elif cmd == "report":
        for pr in (sys.argv[2:] or list(prs)):
            st = state.get(pr, {})
            meta = pr_view(pr, "state,headRefOid,mergedAt,closed,statusCheckRollup")
            unresolved = [t for t in review_threads(pr) if not t.get("isResolved")]
            print(f"PR {pr} ({prs.get(pr,'?')}) state={meta.get('state','?')} "
                  f"loop-status={st.get('status','?')} attempts={st.get('attempts',0)}")
            print(f"  head {meta.get('headRefOid','?')[:12]}")
            for c in (meta.get("statusCheckRollup") or []):
                name = c.get("name") or c.get("context") or "?"
                res = c.get("conclusion") or c.get("state") or c.get("status") or "?"
                print(f"  check {name}: {res}")
            print(f"  unresolved threads: {len(unresolved)}")
            for t in unresolved:
                last = (((t.get("comments") or {}).get("nodes") or [{}]))[-1]
                who = (last.get("author") or {}).get("login", "?")
                body = " ".join((last.get("body") or "").split())[:120]
                flag = " [outdated]" if t.get("isOutdated") else ""
                print(f"    {t.get('path')}:{t.get('line')} @{who}{flag} — {body}")
            wt = worktree_for(prs.get(pr, ""))
            dirty = subprocess.run(["git", "-C", wt, "status", "--porcelain"],
                                   capture_output=True, text=True)
            print(f"  worktree {wt}: " +
                  (f"{len(dirty.stdout.splitlines())} dirty file(s)"
                   if dirty.returncode == 0 else "unavailable"))

    else:
        print("unknown command", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
