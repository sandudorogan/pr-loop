"""The scope lane (from PR Lens): every PR I review or work on gets a blind summary of what it changes and a judge's
verdict on how that matches what it claims. One `scopes` row per PR; the queue snapshot carries it (api.md §3.2).

  new head ─▶ own diff unchanged? ── yes ─▶ keep the summary, move `of` to the head
                    │ no
                    ▼
               pr_scope.py ─▶ ready · failed (retried up to MAX_ERRORS) · limited (retried, not counted)

The lane runs beside review and fix and never in their way: its own pool, no per-PR lock, no `runs` row.
"""
import json, subprocess, sys

from pr_loop import db, queue as q
from pr_loop.names import PR_SCOPE

MAX_ERRORS = 3
EMPTY = {"verdict": None, "reason": None, "intent": None, "stated": None, "changes": [], "touches": []}


def due(pr, row):
    """No summary at this head: never tried, a new head, a pass a restart cut short, or a failure with tries left."""
    return (not row or row["sha"] != pr["headRefOid"] or row["status"] in ("running", "limited")
            or row["status"] == "failed" and row["errors"] < MAX_ERRORS)


def item(row, head):
    """The §3.2 `scope` of one item: the last summary, and the state of the pass on the head."""
    return row and {"status": row["status"], "head": row["of"], "current": row["of"] == head, "error": row["error"],
                    "at": row["at"], **(row["summary"] or EMPTY)}


def run(pr, first):
    repo, n, head = pr["repo"], pr["number"], pr["headRefOid"]
    row = db.scope(repo, n)
    try:
        with q.GIT:
            files = q.fingerprint(pr)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return q.log(repo, n, f"scope: git failed: {str(getattr(e, 'stderr', '') or e).strip()[-200:]}")
    if row.get("summary") and row["files"] == files:
        db.put_scope(repo, n, row | {"sha": head, "of": head, "status": "ready", "error": None, "errors": 0, "at": db.now()})
        return q.log(repo, n, "scope unchanged: own diff unchanged")
    db.put_scope(repo, n, row | {"sha": head, "status": "running", "at": db.now()})
    q.log(repo, n, f"scope {head[:12]}: {pr['title']}")
    try:
        out = subprocess.run([sys.executable, PR_SCOPE, "run", "--pr", str(n), "--head", head], **q.child(repo),
                             stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=2 * q.cfg()["scope"]["timeout_s"] + 300)
    except subprocess.TimeoutExpired:
        out = None
    if out and out.returncode == 0:
        summary = json.loads(out.stdout)
        db.put_scope(repo, n, {"sha": head, "of": head, "status": "ready", "summary": summary, "files": files})
        return q.log(repo, n, f"scope {summary['verdict']}: {summary['reason']}")
    limited = bool(out) and out.returncode == 2
    error = "pr_scope.py timed out" if out is None else \
        (out.stderr.strip().splitlines() or ["pr_scope.py printed nothing"])[-1][-300:]
    errors = (row.get("errors", 0) if row.get("sha") == head else 0) + (not limited)
    status = "limited" if limited else "failed"
    db.put_scope(repo, n, row | {"sha": head, "status": status, "error": error, "errors": errors, "at": db.now()})
    q.log(repo, n, f"scope {status}: {error}")
