"""Every repo, label and path that the daemon and the review scripts use, and the move of today's JSON into state.db."""
import fcntl, json, os, re, shutil
from datetime import datetime
from glob import glob

HOME = os.path.expanduser("~")
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CONTRACT = os.path.join(os.path.dirname(ROOT), "contract")
REVIEW_DIR = os.path.join(ROOT, "review")
PR_REVIEW = os.path.join(REVIEW_DIR, "pr_review.py")
PR_FIX = os.path.join(REVIEW_DIR, "pr_fix.py")

MONOREPO = "iprally/iprally"
REPOS = {MONOREPO: {"root": f"{HOME}/workdir/iprally"}, "iprally/gitops": {"root": f"{HOME}/workdir/gitops"}}
LABEL = "local.pr-loop"
NO_REVIEW, NO_FIX = "no-auto-review", "no-auto-fix"

STATE_DIR = f"{HOME}/.local/state"
STATE, FIXES, NEXT, LOCK, LOCKS, NOWS = ".json", ".fixes.json", ".next", ".lock", ".locks", ".now.d"
LOOP = f"{STATE_DIR}/pr-loop"
DB = f"{LOOP}/state.db"
SCRATCH = f"{LOOP}/scratch"
SOCKET = f"{LOOP}/api.sock"
LABEL_FILE = f"{LOOP}/launchd-label"
DAEMON_LOCK, DAEMON_PID = f"{LOOP}/daemon.lock", f"{LOOP}/daemon.pid"
OLD_DAEMON_LOCK = f"{STATE_DIR}/review-queue{LOCK}"
LOG = f"{HOME}/Library/Logs/pr-loop.log"
DELEGATOR = f"{HOME}/.claude/skills/delegator"
BRIEFS = f"{DELEGATOR}/briefs"
CLEAN_CACHE = f"{DELEGATOR}/.clean-reviews.json"


def write_label():
    with open(LABEL_FILE, "w") as fh:
        fh.write(f"{LABEL}\n")


def tag(repo):
    return "" if repo == MONOREPO else f"-{repo.split('/')[1]}"


def path(repo, kind):
    return f"{STATE_DIR}/review-queue{tag(repo)}{kind}"


def fix_dir(repo):
    return f"{STATE_DIR}/pr-fix{tag(repo)}"


def lock(repo, n, kind=""):
    return f"{LOOP}/locks/{repo}/{n}{kind}"


def slot(i):
    return f"{LOOP}/slot.{i}.lock"


def root(repo):
    return REPOS[repo]["root"]


def worktrees(repo_root):
    return os.path.join(repo_root, ".claude", "worktrees")


def env_repo():
    return os.environ.get("PR_LOOP_REPO") or os.environ.get("IPR_REPO", MONOREPO)


def env_root(repo):
    return os.environ.get("PR_LOOP_REPO_ROOT") or os.environ.get("IPR_REPO_ROOT", f"{HOME}/workdir/{repo.split('/')[1]}")


def legacy():
    """Today's JSON state: {rows: {repo: {table: rows}}, files, scratch, ephemera}. The old daemon lock and pid stay."""
    read = lambda p, empty: json.load(open(p)) if os.path.exists(p) else empty
    found = {"rows": {}, "files": [], "scratch": [], "ephemera": []}
    for repo in REPOS:
        states = sorted(f for f in glob(f"{fix_dir(repo)}/*.json") if re.fullmatch(r"\d+\.json", os.path.basename(f)))
        found["rows"][repo] = {
            "reviews": read(path(repo, STATE), {}), "fixes": read(path(repo, FIXES), {}),
            "fix_state": {os.path.basename(f)[:-5]: json.load(open(f)) for f in states},
            "clean_reviews": read(CLEAN_CACHE, {}) if repo == MONOREPO else {}, "next": read(path(repo, NEXT), [])}
        found["files"] += [p for p in (path(repo, STATE), path(repo, FIXES), path(repo, NEXT)) if os.path.exists(p)]
        found["files"] += states
        found["scratch"] += [d for d in glob(f"{fix_dir(repo)}/[0-9]*-*") if os.path.isdir(d)]
        found["ephemera"] += [p for p in (path(repo, STATE + LOCK), path(repo, FIXES + LOCK), path(repo, LOCKS),
                                          path(repo, NOWS)) if os.path.exists(p)] + glob(f"{fix_dir(repo)}/*.lock")
    found["files"] += [CLEAN_CACHE] if os.path.exists(CLEAN_CACHE) else []
    return found


def counts(rows):
    return {repo: {table: sum(map(len, data.values())) if table == "clean_reviews" else len(data)
                   for table, data in tables.items()} for repo, tables in rows.items()}


def migrate(dry_run=False):
    """Imports today's JSON state into state.db in one transaction, once. Then the imported files move to
    legacy/<timestamp>/ under their path from HOME, the fix scratch dirs to scratch/, and the locks and
    live-run files go. Returns what it did (dry_run: would do), or {} once the import has happened."""
    from pr_loop import db
    if dry_run:
        found = {} if os.path.exists(DB) and db.meta_get("imported_at") else legacy()
        return found and {**found, "rows": counts(found["rows"])}
    os.makedirs(LOOP, exist_ok=True)
    with open(f"{LOOP}/.migrate.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        if db.meta_get("imported_at"):
            return {}
        found, stamp = legacy(), datetime.now()
        with db.tx():
            for repo, t in found["rows"].items():
                for n, entry in t["reviews"].items():
                    db.put_review(repo, n, entry)
                for n, entry in t["fixes"].items():
                    db.put_fix(repo, n, entry)
                for n, state in t["fix_state"].items():
                    db.put_fix_state(repo, n, state)
                for head, reviewers in t["clean_reviews"].items():
                    for reviewer in reviewers:
                        db.add_clean(repo, *head.split("/"), reviewer)
                db.bump(repo, *t["next"])
            db.meta_set("imported_at", stamp.astimezone().isoformat(timespec="seconds"))
        db.log_moves(relocate(found, f"{LOOP}/legacy/{stamp:%Y%m%d%H%M%S}"))
    return {**found, "rows": counts(found["rows"])}


def relocate(found, legacy_dir):
    moves = [(old, os.path.join(legacy_dir, os.path.relpath(old, HOME)), "imported") for old in found["files"]]
    moves += [(old, os.path.join(SCRATCH, os.path.basename(old)), "scratch") for old in found["scratch"]]
    for old, new, _ in moves:
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.rename(old, new)
    for old in found["ephemera"]:
        shutil.rmtree(old) if os.path.isdir(old) else os.remove(old)
    for d in {fix_dir(repo) for repo in REPOS}:
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    return moves + [(old, None, "deleted") for old in found["ephemera"]]


def reverse():
    """Writes the current state.db back to today's files, with the old writers' format, then sets the db aside
    as state.db.reverted-<timestamp>. Returns the files it wrote."""
    from pr_loop import db
    if not os.path.exists(DB):
        raise SystemExit(f"no {DB} to export")
    written = []

    def write(p, data, indent=2):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump(data, fh, indent=indent)
        written.append(p)

    with open(f"{LOOP}/.migrate.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        for repo in REPOS:
            write(path(repo, STATE), {str(n): e for n, e in db.reviews(repo).items()})
            write(path(repo, FIXES), {str(n): e for n, e in db.fixes(repo).items()})
            write(path(repo, NEXT), db.next_list(repo), None)
            for n, state in db.fix_states(repo).items():
                write(f"{fix_dir(repo)}/{n}.json", state)
        write(CLEAN_CACHE, {f"{n}/{sha}": reviewers for (_, n, sha), reviewers in db.cleared().items()})
        db.close()
        os.rename(DB, f"{DB}.reverted-{datetime.now():%Y%m%d%H%M%S}")
    return written
