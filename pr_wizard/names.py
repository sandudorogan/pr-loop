"""Every repo, label and path that the daemon and the review scripts use."""
import os

HOME = os.path.expanduser("~")
REVIEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "review")
PR_REVIEW = os.path.join(REVIEW_DIR, "pr_review.py")
PR_FIX = os.path.join(REVIEW_DIR, "pr_fix.py")

MONOREPO = "iprally/iprally"
REPOS = {MONOREPO: {"root": f"{HOME}/workdir/iprally", "review": True},
         "iprally/gitops": {"root": f"{HOME}/workdir/gitops", "review": False}}
LABEL = "local.review-queue"
NO_REVIEW, NO_FIX = "no-auto-review", "no-auto-fix"

STATE_DIR = f"{HOME}/.local/state"
STATE, FIXES, NEXT, LOCK, LOCKS, NOWS, PID = ".json", ".fixes.json", ".next", ".lock", ".locks", ".now.d", ".pid"
DB = f"{STATE_DIR}/pr-wizard/state.db"
LOG = f"{HOME}/Library/Logs/review-queue.log"
NOTIFIER = f"{HOME}/.local/share/review-queue/Review Queue.app/Contents/MacOS/terminal-notifier"
DELEGATOR = f"{HOME}/.claude/skills/delegator"
BRIEFS = f"{DELEGATOR}/briefs"
CLEAN_CACHE = f"{DELEGATOR}/.clean-reviews.json"


def tag(repo):
    return "" if repo == MONOREPO else f"-{repo.split('/')[1]}"


def path(repo, kind):
    return f"{STATE_DIR}/review-queue{tag(repo)}{kind}"


def fix_dir(repo):
    return f"{STATE_DIR}/pr-fix{tag(repo)}"


def root(repo):
    return REPOS[repo]["root"]


def worktrees(repo_root):
    return os.path.join(repo_root, ".claude", "worktrees")


def env_repo():
    return os.environ.get("IPR_REPO", MONOREPO)


def env_root(repo):
    return os.environ.get("IPR_REPO_ROOT", f"{HOME}/workdir/{repo.split('/')[1]}")
