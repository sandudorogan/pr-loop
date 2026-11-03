"""Shared fixtures: the three scripts as modules, and builders for queue PRs and GitHub payloads."""
from pathlib import Path
import atexit
import os
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "review"))
os.environ["PR_WIZARD_CONFIG"] = "/nonexistent/config.json"
if "PR_WIZARD_TEST_HOME" not in os.environ:
    os.environ["PR_WIZARD_TEST_HOME"] = os.environ["HOME"] = tempfile.mkdtemp(prefix="pr-wizard-test-home-")
    atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

from pr_wizard import names, queue as rq  # noqa: E402

assert names.DB.startswith(os.environ["PR_WIZARD_TEST_HOME"]), f"tests would touch the real state at {names.DB}"
import pr_fix, pr_review  # noqa: E402

MONOREPO, GITOPS = rq.MONOREPO, "iprally/gitops"
CHECKOUTS = {repo: where["root"] for repo, where in rq.REPOS.items()}
rq.CHECKOUTS.scan = lambda roots: CHECKOUTS
HEAD = "a" * 40


def pr(number=1, repo=MONOREPO, mine=True, requested=False, head=HEAD, additions=1, labels=(), mergeable="MERGEABLE",
       reviews=0, threads=(), counts=None, approvals=(), committed="2026-10-25T10:00:00+00:00", talk=()):
    """A queue PR as `queue()` returns it. `threads` = [(resolved, comment count)], `counts` = {check state: n},
    `approvals` = [viewer_did_author] of each APPROVED opinionated review, `talk` = [(created, mine, typename)]
    of each PR comment."""
    rollup = {"contexts": {"checkRunCountsByState": [{"state": s, "count": n} for s, n in counts.items()]}} \
        if counts is not None else None
    return {"number": number, "title": f"title {number}", "state": "OPEN", "isDraft": False, "headRefOid": head,
            "baseRefName": "main", "author": {"login": "colleague"}, "additions": additions, "deletions": 0, "viewerDidAuthor": mine,
            "mergeable": mergeable, "repository": {"nameWithOwner": repo}, "repo": repo, "requested": requested,
            "labels": {"nodes": [{"name": l} for l in labels]},
            "latestOpinionatedReviews": {"nodes": [{"state": "APPROVED", "viewerDidAuthor": a} for a in approvals]},
            "commits": {"nodes": [{"commit": {"committedDate": committed, "statusCheckRollup": rollup}}]},
            "reviews": {"totalCount": reviews},
            "reviewThreads": {"nodes": [{"isResolved": r, "comments": {"totalCount": c}} for r, c in threads]},
            "comments": {"nodes": [{"createdAt": t, "viewerDidAuthor": m, "author": {"__typename": k}}
                                   for t, m, k in talk]}}


def finding(severity="medium", confidence=0.9, file="a.py", line_start=2, line_end=None, title="t"):
    return {"severity": severity, "confidence": confidence, "file": file, "line_start": line_start,
            "line_end": line_end, "title": title, "body": "body", "recommendation": "fix it"}


def check_run(name="build", conclusion="failure", job=1, run=99):
    return {"id": job, "name": name, "conclusion": conclusion, "app": {"slug": "github-actions"},
            "html_url": f"https://github.com/o/r/actions/runs/{run}/job/{job}"}
