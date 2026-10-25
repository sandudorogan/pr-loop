"""Reviews my own open PRs and the ones that wait on me, three at a time, then stays quiet until their own diff changes.

Usage:
  review-queue --daemon     launchd keeps this alive: 3 workers review, 3 fix my PRs, the queue refreshes every 5 min
  review-queue              run one review tick now, in this terminal, beside the daemon
  review-queue --pr 16400   review one PR now, even if its own diff is unchanged
  review-queue -n           dry run: print each PR's gate decision, review nothing
  review-queue -l           list the queue: ▶ in review or fix, 1..n review order, ✓ ready to approve
  review-queue --next 16400 move a PR to the front of the review order
  review-queue --wait 16400 16401   block until one of these PRs settles at its current head, print it
  review-queue --bg         refresh the daemon's queue now (starts the daemon if it is down)
  review-queue --prune      remove the worktrees of PRs that merged or that I approved (-n: dry run)

One GraphQL call lists the queue: my own open PRs, review requests, and PRs I reviewed. Local
gates (head sha, own-diff fingerprint) drop every PR with nothing new, so the reviewers in
pr_review.py run only on new code. A push re-enters the queue at once: CI is never awaited.
After ROUNDS rounds in a row with findings, a PR waits for a human. A PR of mine that came out
clean is held: later pushes (say, for a colleague's feedback) get a review only on request.

The fix lane runs pr_fix.py (headless Codex) on my own PRs once the reviewers are done with the
head and the PR carries feedback no fix pass has seen: a new review, thread comment or resolve.
A push from it is the next review round.

Labels opt a PR out: no-auto-review skips the reviewers (the fix lane then acts on feedback alone),
no-auto-fix keeps the fix lane off it. --pr N reviews a labeled PR anyway.

One process serves every repo in REPOS: iprally/iprally gets both lanes, iprally/gitops the fix lane alone.
--pr, --next and --wait act on --repo, else $IPR_REPO, else iprally/iprally.
The daemon prunes the worktrees of every repo at start and every 30 min; --prune does one pass (--repo: that repo only).

  my PR head ──▶ review (3) ──settled──▶ fix (3) ──pushed──▶ new head ─┐
       ▲                                    │ nothing pushed → stop     │
       └────────────────────────────────────────────────────────────────┘
Log: ~/Library/Logs/review-queue.log
"""
import argparse, fcntl, hashlib, json, os, re, signal, subprocess, sys, threading, time, traceback
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fnmatch import fnmatch
from glob import glob

HOME = os.path.expanduser("~")
REVIEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "review")
PR_REVIEW = os.path.join(REVIEW_DIR, "pr_review.py")
PR_FIX = os.path.join(REVIEW_DIR, "pr_fix.py")
MONOREPO = "iprally/iprally"
REPOS = {MONOREPO: {"root": f"{HOME}/workdir/iprally", "review": True},
         "iprally/gitops": {"root": f"{HOME}/workdir/gitops", "review": False}}
STATE_DIR = f"{HOME}/.local/state"
STATE, FIXES, NEXT, LOCK, LOCKS, NOWS, PID = ".json", ".fixes.json", ".next", ".lock", ".locks", ".now.d", ".pid"
LOG = f"{HOME}/Library/Logs/review-queue.log"
LABEL = "local.review-queue"
PR_NUMBER = re.compile(r"(?:fix|sync|review)-(\d{4,})")
NOTIFIER = f"{HOME}/.local/share/review-queue/Review Queue.app/Contents/MacOS/terminal-notifier"

REVIEWERS = ("opus", "codex", "quality")
WORKERS = 3
FIX_WORKERS = 3
FIX_TIMEOUT = 4 * 3600
FIX_ERRORS = 3
REFRESH = 300
PRUNE_EVERY = 1800
IDLE_REFRESH = 60
LIST_CACHE = "30s"
ATTEMPTS = 3
BACKOFF = (60, 180)
MAX_ADDED = 4000
ROUNDS = 8
WAIT_POLL = 30
READY = ("clean", "quality-only")
SETTLED = ("nothing-to-fix", "refuted-only", "no-changes")
NO_REVIEW, NO_FIX = "no-auto-review", "no-auto-fix"
LIMITED = object()
TRIVIAL = ("*.lock", "*lock.json", "*.lockb", "*.md", "*.png", "*.jpg", "*.svg")
FALSE_CLEAN = re.compile(
    r"overloaded|api error|rate.?limit|no review (report|content)|not provided|^\(none\)$", re.I)

CLEAN_NOTICE = ("Automatic review pipeline ran on `{sha}`. None of the Opus code review, "
                "quality self-review or Codex code review found anything to fix. PR good to go.")

FRAGMENT = """
fragment pr on PullRequest {
  number title state isDraft headRefOid baseRefName additions deletions viewerDidAuthor mergeable
  repository { nameWithOwner }
  labels(first: 20) { nodes { name } }
  latestOpinionatedReviews(first: 20) { nodes { state viewerDidAuthor } }
  commits(last: 1) { nodes { commit { committedDate statusCheckRollup {
    contexts(first: 0) { checkRunCountsByState { state count } } } } } }
  reviews { totalCount }
  reviewThreads(first: 100) { nodes { isResolved comments { totalCount } } }
}"""
QUEUE_QUERY = """
query($mine: String!, $requested: String!, $reviewed: String!) {
  mine: search(query: $mine, type: ISSUE, first: 50) { nodes { ...pr } }
  requested: search(query: $requested, type: ISSUE, first: 50) { nodes { ...pr } }
  reviewed: search(query: $reviewed, type: ISSUE, first: 50) { nodes { ...pr } }
}""" + FRAGMENT
WORKTREE_FRAGMENT = """
fragment done on PullRequest {
  number state headRefOid
  latestOpinionatedReviews(first: 20) { nodes { state viewerDidAuthor } }
  reviewRequests(first: 20) { nodes { requestedReviewer { ... on User { isViewer } } } }
}"""
PR_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { ...pr } }
}""" + FRAGMENT


GUARD, GIT = threading.Lock(), threading.Lock()
ACTIVE, NOTED = {}, {}


def tag(repo):
    return "" if repo == MONOREPO else f"-{repo.split('/')[1]}"


def path(repo, kind):
    return f"{STATE_DIR}/review-queue{tag(repo)}{kind}"


def root(repo):
    return REPOS[repo]["root"]


def child(repo):
    return {"env": {**os.environ, "IPR_REPO": repo, "IPR_REPO_ROOT": root(repo)}, "cwd": root(repo)}


def pr_key(pr):
    return pr["repo"], pr["number"]


def log(repo, pr, msg):
    line = f"{datetime.now():%F %T}  {tag(repo)[1:]}#{pr:<6} {msg}"
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    if sys.stdout.isatty():
        with open(LOG, "a") as fh:
            fh.write(line + "\n")


def say(msg):
    log(MONOREPO, "-", msg)


def url(repo, pr):
    return f"https://github.com/{repo}/pull/{pr}"


def escaped(message):
    return f"\\{message}" if message[:1] in "[({'\"" else message


def ready_alert(repo, pr, title):
    review_notifier(repo, pr, "-title", "Ready for your approval", "-subtitle", f"#{pr}",
                    "-message", escaped(title), "-open", url(repo, pr), "-sound", "default")


def drop_ready_alert(repo, pr):
    review_notifier(repo, pr, "-remove", f"review-queue{tag(repo)}-{pr}")


def review_notifier(repo, pr, *args):
    out = subprocess.run([NOTIFIER, "-group", f"review-queue{tag(repo)}-{pr}", *args], capture_output=True, text=True)
    if out.returncode:
        log(repo, pr, f"Review Queue notifier failed: {(out.stderr or out.stdout).strip()}")


def sh(*args, repo=MONOREPO):
    return subprocess.run(args, cwd=root(repo), capture_output=True, text=True,
                          timeout=600, check=True).stdout


def load(repo, kind=STATE):
    try:
        return json.load(open(path(repo, kind)))
    except (OSError, ValueError):
        return {}


def bumped(repo):
    try:
        return json.load(open(path(repo, NEXT)))
    except (OSError, ValueError):
        return []


def bumps():
    return {repo: bumped(repo) for repo in REPOS}


def save_bumped(repo, prs):
    with open(f"{path(repo, NEXT)}.tmp", "w") as fh:
        json.dump(prs, fh)
    os.replace(f"{path(repo, NEXT)}.tmp", path(repo, NEXT))


def priority(pr, first):
    """Bumped PRs first, then mine, then the rest."""
    mine = first.get(pr["repo"], [])
    return pr["number"] not in mine, mine.index(pr["number"]) if pr["number"] in mine else 0, not pr["viewerDidAuthor"]


def save(state, file):
    with open(f"{file}.tmp", "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(f"{file}.tmp", file)


def tagged(pr, requested):
    return dict(pr, repo=pr["repository"]["nameWithOwner"], requested=requested)


def pr_of(repo, n):
    owner, name = repo.split("/")
    pr = json.loads(sh("gh", "api", "graphql", "-f", f"query={PR_QUERY}", "-f", f"owner={owner}",
                       "-f", f"name={name}", "-F", f"number={n}", repo=repo))["data"]["repository"]["pullRequest"]
    return [tagged(pr, True)] if pr["state"] == "OPEN" else []


def queue(*flags):
    """My own PRs and review requests (drafts too), plus PRs I reviewed before, since a posted
    review drops the request, in every repo of REPOS. `flags` go to the `gh api` call."""
    scope = " ".join(f"repo:{repo}" for repo in REPOS) + " is:pr is:open"
    data = json.loads(sh("gh", "api", "graphql", *flags, "-f", f"query={QUEUE_QUERY}",
                         "-f", f"mine={scope} author:@me",
                         "-f", f"requested={scope} user-review-requested:@me",
                         "-f", f"reviewed={scope} reviewed-by:@me -author:@me"))["data"]
    found = lambda search: [tagged(p, False) for p in data[search]["nodes"]]
    requested = {pr_key(p) for p in found("requested")}
    prs = {pr_key(p): p for p in found("reviewed") + found("requested") + found("mine")}
    return [dict(p, requested=k in requested) for k, p in sorted(prs.items())]


def approved(pr):
    """My approval stands and nobody re-requested my review since."""
    return not pr["requested"] and any(
        r["viewerDidAuthor"] and r["state"] == "APPROVED" for r in pr["latestOpinionatedReviews"]["nodes"])


def labeled(pr, label):
    return any(l["name"] == label for l in pr["labels"]["nodes"])


def unreviewed(pr):
    """The review prompts carry the monorepo's conventions: another repo gets the fix lane alone."""
    return not REPOS[pr["repo"]]["review"] or labeled(pr, NO_REVIEW)


def colleague_approved(pr):
    return any(not r["viewerDidAuthor"] and r["state"] == "APPROVED" for r in pr["latestOpinionatedReviews"]["nodes"])


def baselined(pr, requested):
    """A first sighting that only records the head: a PR I reviewed by hand, or a PR of mine a colleague approved."""
    return not requested and (not pr["viewerDidAuthor"] or colleague_approved(pr))


def fingerprint(pr):
    """{path: hash of its +/- lines} over the PR's own diff — a merge of main or a rebase keeps it."""
    sh("git", "fetch", "-q", "--no-tags", "origin", pr["baseRefName"], pr["headRefOid"], repo=pr["repo"])
    diff = sh("git", "diff", "--no-color", "--no-ext-diff", f"origin/{pr['baseRefName']}...{pr['headRefOid']}",
              repo=pr["repo"])
    files = {}
    for chunk in re.split(r"^diff --git ", diff, flags=re.M)[1:]:
        lines = chunk.splitlines(True)
        body = "".join(l for l in lines if l[:1] in "+-" and not l.startswith(("+++", "---")))
        files[lines[0].rstrip().rsplit(" b/", 1)[-1]] = hashlib.sha1(body.encode()).hexdigest()
    return files


def false_clean(res):
    """A reviewer that never ran can still report "no findings" — its summary gives it away."""
    summary = (res.get("summary") or "").strip()
    return res.get("reason") == "no-findings" and (len(summary) < 40 or bool(FALSE_CLEAN.search(summary)))


def run_reviewer(repo, pr, reviewer):
    force = []
    for i in range(ATTEMPTS):
        if i:
            log(repo, pr, f"{reviewer} retry in {BACKOFF[i - 1]} s")
            time.sleep(BACKOFF[i - 1])
        log(repo, pr, f"{reviewer} attempt {i + 1}/{ATTEMPTS} started{' (--force)' if force else ''}")
        start = time.monotonic()
        out = subprocess.run([sys.executable, PR_REVIEW, "run", "--pr", str(pr), "--reviewer", reviewer, *force],
                             **child(repo), stdin=subprocess.DEVNULL, capture_output=True, text=True)
        try:
            res = json.loads(out.stdout)
        except ValueError:
            res = None
        if out.returncode == 0 and res and not false_clean(res):
            via = f" on {res['engine']}" if "usage limit" in out.stderr else ""
            log(repo, pr, f"{reviewer} done{via} in {time.monotonic() - start:.0f} s: {outcome(res)}")
            return res
        if "both at their usage limit" in out.stderr:
            log(repo, pr, f"{reviewer} stopped: claude and codex are both at their usage limit")
            return LIMITED
        force = force or (["--force"] if res and false_clean(res) else [])
        why = (out.stderr.strip() or out.stdout.strip())[-300:].replace("\n", " ⏎ ")
        log(repo, pr, f"{reviewer} attempt {i + 1}/{ATTEMPTS} failed: {why}")


def outcome(res):
    if res.get("posted"):
        return f"posted {res.get('findings')} finding(s), {res.get('inline')} inline — {res.get('url')}"
    return f"{res.get('skipped') or res.get('reason')} — {(res.get('summary') or res.get('message') or '').strip()[:160]}"


def review(repo, pr):
    with ThreadPoolExecutor(len(REVIEWERS)) as pool:
        results = dict(zip(REVIEWERS, pool.map(lambda r: run_reviewer(repo, pr, r), REVIEWERS)))
    limited = [r for r, res in results.items() if res is LIMITED]
    if limited:
        return "limited", f"{', '.join(limited)} hit the usage limit of both engines"
    failed = [r for r, res in results.items() if res is None]
    if failed:
        return "failed", f"{', '.join(failed)} failed {ATTEMPTS}×"
    flagged = [r for r, res in results.items() if not res.get("stop")]
    return ("posted", ", ".join(flagged)) if flagged else ("clean", "no findings")


def post_clean_notice(repo, pr, sha):
    try:
        sh("gh", "api", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={CLEAN_NOTICE.format(sha=sha[:12])}",
           repo=repo)
        log(repo, pr, "clean notice posted")
    except subprocess.CalledProcessError as e:
        log(repo, pr, f"clean notice failed: {e.stderr.strip()[-200:]}")


def decide(pr, seen, files, only):
    """(status, note) for a PR that nothing reviews, or None to review it."""
    if only:
        return None
    if not seen and baselined(pr, pr["requested"]):
        return "baseline", ("approved by a colleague" if pr["viewerDidAuthor"] else "reviewed by me before") \
            + " — watching from this head on"
    changed = {f for f in files.keys() | seen.get("files", {}).keys()
               if files.get(f) != seen.get("files", {}).get(f)}
    if seen and not changed:
        return "unchanged", "own diff unchanged (merge of base or rebase)"
    if seen and all(any(fnmatch(f, g) for g in TRIVIAL) for f in changed):
        return "trivial", f"only trivial files: {', '.join(sorted(changed))}"
    if seen.get("hold") and not pr["requested"]:
        return "held", f"clean before, review only on request: --next {pr['number']} or --pr {pr['number']}"
    if seen.get("rounds", 0) >= ROUNDS:
        return "needs-human", f"{ROUNDS} rounds in a row with findings, review it by hand or run --pr {pr['number']}"
    if pr["additions"] > MAX_ADDED:
        return "too-big", f"{pr['additions']} added lines, review it by hand"


def log_once(repo, n, msg):
    """Log a skip once per reason, not on every refresh."""
    if NOTED.get((repo, n)) != msg:
        NOTED[repo, n] = msg
        log(repo, n, msg)


def in_review(repo, n, on, lane="review"):
    with GUARD:
        if on:
            ACTIVE[repo, n] = f"{lane} {datetime.now():%T}"
        else:
            del ACTIVE[repo, n]
        os.makedirs(path(repo, NOWS), exist_ok=True)
        with open(f"{path(repo, NOWS)}/{os.getpid()}.json", "w") as fh:
            json.dump({k: v for (r, k), v in ACTIVE.items() if r == repo}, fh)


def record(repo, key, entry, kind=STATE):
    """Merge one PR's entry under a file lock: the daemon and a manual run may both write."""
    with open(f"{path(repo, kind)}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load(repo, kind)
        state[key] = entry
        save(state, path(repo, kind))


@contextmanager
def claimed(repo, n):
    """True while this process holds PR n; a second run skips it instead of reviewing it twice."""
    os.makedirs(path(repo, LOCKS), exist_ok=True)
    with open(f"{path(repo, LOCKS)}/{n}", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def handle(pr, first, only, dry_run):
    pr["requested"] = pr["requested"] or pr["number"] in first
    repo, n, key = pr["repo"], pr["number"], str(pr["number"])
    seen = load(repo).get(key, {})
    if pr["requested"] and seen.get("status") == "baseline":
        seen = {}
    if approved(pr) and not only:
        return log_once(repo, n, "approved by me, not re-requested")
    if unreviewed(pr) and not only:
        return log_once(repo, n, NO_REVIEW)
    if seen.get("sha") == pr["headRefOid"] and seen.get("status") != "limited" and not only:
        return log_once(repo, n, f"same head {pr['headRefOid'][:12]} ({seen['status']} {seen['at']})")
    try:
        with GIT:
            files = fingerprint(pr)
    except subprocess.CalledProcessError as e:
        return log(repo, n, f"git failed: {e.stderr.strip()[-200:]}")
    except subprocess.TimeoutExpired as e:
        return log(repo, n, f"git {e.cmd[1]} timed out after {e.timeout:.0f} s")

    skip = decide(pr, seen, files, only)
    if dry_run:
        return log(repo, n, f"{skip[0]}: {skip[1]}" if skip else f"would review: {pr['title']}")
    if skip:
        status, note = skip
    else:
        log(repo, n, f"reviewing {pr['headRefOid'][:12]}: {pr['title']}")
        drop_ready_alert(repo, n)
        in_review(repo, n, True)
        status, note = review(repo, n)
        in_review(repo, n, False)
    log(repo, n, f"{status}: {note}" + (", retrying on the next refresh" if status == "limited" else ""))
    verdict = {"clean": "clean", "posted": "quality-only" if note == "quality" else "posted"}.get(
        status, seen.get("verdict") if status in ("unchanged", "trivial", "limited") else None)
    if status == "clean":
        post_clean_notice(repo, n, pr["headRefOid"])
    if status in ("clean", "posted") and verdict in READY and not pr["viewerDidAuthor"]:
        ready_alert(repo, n, pr["title"])
    absorbed = status in ("posted", "clean", "baseline", "unchanged", "trivial")
    rounds = 0 if status == "clean" else (0 if only else seen.get("rounds", 0)) + (status == "posted")
    hold = status == "clean" and pr["viewerDidAuthor"] if status in ("posted", "clean") else seen.get("hold", False)
    record(repo, key, {"sha": pr["headRefOid"], "status": status, "verdict": verdict, "note": note, "rounds": rounds,
                       "hold": hold,
                       "at": f"{datetime.now():%F %T}", "files": files if absorbed else seen.get("files", {})})
    if n in first and status != "limited":
        with GUARD:
            save_bumped(repo, [x for x in bumped(repo) if x != n])
    if status == "posted" and pr["viewerDidAuthor"]:
        kick()


def feedback_key(pr):
    """Moves when a review, a thread comment or a resolve lands, the head moves, the base conflicts, a check
    run fails or a red head's runs all finish (a refuted job reruns only then)."""
    threads = [t["comments"]["totalCount"] for t in pr["reviewThreads"]["nodes"] if not t["isResolved"]]
    conflict = ":conflict" if pr["mergeable"] == "CONFLICTING" else ""
    rollup = pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"] or {"contexts": {"checkRunCountsByState": []}}
    counts = {c["state"]: c["count"] for c in rollup["contexts"]["checkRunCountsByState"]}
    failed = counts.get("FAILURE", 0) + counts.get("TIMED_OUT", 0)
    running = "-running" if any(counts.get(s) for s in ("QUEUED", "PENDING", "WAITING", "IN_PROGRESS")) else ""
    ci = f":ci-red-{failed}{running}" if failed else ""
    return f"{pr['headRefOid']}:{pr['reviews']['totalCount']}:{len(threads)}:{sum(threads)}{conflict}{ci}"


def fixable(pr, state, fixes):
    """My PR whose head the reviewers are done with (or skip), carrying feedback, a conflict or red CI no fix
    pass has seen."""
    seen = state.get(str(pr["number"]), {})
    reviewed = unreviewed(pr) or seen.get("sha") == pr["headRefOid"] and seen.get("status") != "limited"
    return (pr["viewerDidAuthor"] and not labeled(pr, NO_FIX) and reviewed
            and fixes.get(str(pr["number"]), {}).get("key") != feedback_key(pr))


def fixing(pr, state, fixes):
    """The fix lane still owes this head a pass: the reviewers posted and no pass ran on it yet, or
    the last one errored or went red and will run again."""
    fixed = fixes.get(str(pr["number"]), {})
    return (pr["viewerDidAuthor"] and not labeled(pr, NO_FIX)
            and state.get(str(pr["number"]), {}).get("status") == "posted"
            and (fixed.get("sha") != pr["headRefOid"] or not fixed.get("key")))


def ready(pr, seen, fixed):
    """Clean for good: a clean review, or a fix pass on my posted head that left nothing to push. On my PR,
    a fix pass on the head that did not settle (red CI it could not land a fix for) overrides a clean review."""
    if pr["viewerDidAuthor"] and (seen.get("status") == "posted" or fixed.get("sha") == pr["headRefOid"]):
        return fixed.get("sha") == pr["headRefOid"] and fixed.get("status") in SETTLED
    return seen.get("verdict") in READY


def fix_note(res, err):
    status = res.get("status", "error")
    if status == "pushed":
        merged = "merged the base, " if res.get("merged") else ""
        return f"pushed {res['pushed'][:12]}: {merged}{res['fixed']} fixed, {res['refuted']} refuted, {res['deferred']} deferred"
    if status == "tests-red":
        return f"Karma red in {', '.join(res['failing'])} — {res['worktree']}"
    if status == "error":
        return (err.strip().splitlines() or ["pr_fix.py printed nothing"])[-1][-200:]
    return (res.get("summary") or status).strip()[:160]


def fix(pr, first):
    repo, n, head = pr["repo"], pr["number"], pr["headRefOid"]
    log(repo, n, f"fixing {head[:12]}: {pr['title']}")
    in_review(repo, n, True, "fix")
    try:
        out = subprocess.run([sys.executable, PR_FIX, "run", "--pr", str(n)], **child(repo), capture_output=True,
                             text=True, timeout=FIX_TIMEOUT)
    finally:
        in_review(repo, n, False)
    try:
        res = json.loads(out.stdout)
    except ValueError:
        res = {}
    status, note = res.get("status", "error"), fix_note(res, out.stderr)
    log(repo, n, f"fix {status}: {note}" + (", retrying on the next refresh" if status == "limited" else ""))
    if status == "limited":
        return
    errors = load(repo, FIXES).get(str(n), {}).get("errors", 0) + 1 if status in ("error", "tests-red") else 0
    record(repo, str(n), {"sha": head, "key": feedback_key(pr) if not errors or errors >= FIX_ERRORS else None,
                          "status": status, "note": note, "errors": errors, "at": f"{datetime.now():%F %T}"}, FIXES)
    if status == "pushed":
        kick()


class Pending:
    """The PRs from the latest queue fetch that no worker has taken yet, keyed by (repo, number)."""

    def __init__(self, prs=(), workers=WORKERS):
        self.prs, self.busy, self.cond, self.workers = list(prs), set(), threading.Condition(), workers

    def refill(self, prs):
        with self.cond:
            self.prs = [pr for pr in prs if pr_key(pr) not in self.busy]
            self.cond.notify_all()

    def take(self, wait):
        with self.cond:
            while not self.prs:
                if not wait:
                    return None
                self.cond.wait()
            first = bumps()
            pr = min(self.prs, key=lambda p: priority(p, first))
            self.prs.remove(pr)
            self.busy.add(pr_key(pr))
            return pr, first[pr["repo"]]

    def done(self, key):
        with self.cond:
            self.busy.discard(key)

    def idle(self):
        with self.cond:
            return not self.prs and len(self.busy) < self.workers


def work(pending, wait, job):
    while picked := pending.take(wait):
        repo, n = key = pr_key(picked[0])
        try:
            with claimed(repo, n) as mine:
                if mine:
                    job(*picked)
                else:
                    log_once(repo, n, "handled by another run")
        except Exception:
            log(repo, n, f"crashed: {traceback.format_exc().strip()[-300:]}".replace("\n", " ⏎ "))
        finally:
            pending.done(key)


def run(pending, wait, job):
    with ThreadPoolExecutor(pending.workers) as pool:
        for _ in range(pending.workers):
            pool.submit(work, pending, wait, job)


def reviewer(only, dry_run):
    return lambda pr, first: handle(pr, first, only, dry_run)


def tick(only, dry_run):
    """`only` is (repo, number): review that PR now."""
    started = time.monotonic()
    pending = Pending(pr_of(*only) if only else queue())
    say(f"tick started{' (dry run)' if dry_run else ''}: {len(pending.prs)} PR(s) in queue")
    if only and not pending.prs:
        log(*only, "not an open PR")
    run(pending, False, reviewer(only, dry_run))
    for repo in REPOS:
        if os.path.exists(f"{path(repo, NOWS)}/{os.getpid()}.json"):
            os.remove(f"{path(repo, NOWS)}/{os.getpid()}.json")
    say(f"tick done in {time.monotonic() - started:.0f} s")


def lanes(repo):
    return "review+fix" if REPOS[repo]["review"] else "fix"


def serving(held):
    """The repos this daemon works on. A repo that had its own daemon before stays off while that one still
    holds its lock; `held` keeps the locks taken so far."""
    for repo in REPOS.keys() - held.keys() - {MONOREPO}:
        lock = open(path(repo, LOCK), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held[repo] = lock
        except BlockingIOError:
            lock.close()
            log_once(repo, "-", f"skipped: an old {repo} daemon holds {path(repo, LOCK)}")
    return {MONOREPO, *held}


def daemon():
    """Workers review nonstop. The queue data behind them refreshes every REFRESH s, every IDLE_REFRESH s
    while a worker has nothing to take, and at once on SIGUSR1."""
    lock = open(path(MONOREPO, LOCK), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return say("daemon already running")
    with open(path(MONOREPO, PID), "w") as fh:
        fh.write(str(os.getpid()))
    pending, fixes, refresh_now, held = Pending(), Pending(workers=FIX_WORKERS), threading.Event(), {}
    signal.signal(signal.SIGUSR1, lambda *_: refresh_now.set())

    def refresh():
        idle = False
        while True:
            started = time.monotonic()
            try:
                served = serving(held)
                prs = [pr for pr in queue() if pr["repo"] in served]
                pending.refill(prs)
                state, fixed = {r: load(r) for r in served}, {r: load(r, FIXES) for r in served}
                fixes.refill([pr for pr in prs if fixable(pr, state[pr["repo"]], fixed[pr["repo"]])])
                if not idle:
                    say(f"queue refreshed: {len(prs)} PR(s), {len(pending.busy)} in review, "
                         f"{len(fixes.prs) + len(fixes.busy)} to fix")
            except Exception as e:
                say(f"queue refresh failed: {(getattr(e, 'stderr', None) or str(e)).strip()[-200:]}")
            idle = False
            while not refresh_now.wait(IDLE_REFRESH):
                if time.monotonic() - started >= REFRESH:
                    break
                if pending.idle():
                    idle = True
                    break
            refresh_now.clear()

    say(f"daemon started: {', '.join(f'{repo} {lanes(repo)}' for repo in REPOS)}")
    say(f"{WORKERS} review and {FIX_WORKERS} fix workers, queue refresh every "
         f"{REFRESH // 60} min, every {IDLE_REFRESH} s while a review worker is idle")
    threading.Thread(target=refresh, daemon=True).start()
    threading.Thread(target=run, args=(fixes, True, fix), daemon=True).start()
    start_pruner()
    run(pending, True, reviewer(None, False))


def kick():
    """Ask the daemon for a queue refresh now; False when no daemon runs."""
    try:
        os.kill(int(open(path(MONOREPO, PID)).read()), signal.SIGUSR1)
        return True
    except (OSError, ValueError):
        return False


def wake():
    if not kick():
        subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"], check=True)


def heads(repo, numbers):
    """{pr: {repo, number, state, headRefOid, viewerDidAuthor, labels}} in one GraphQL call."""
    owner, name = repo.split("/")
    fields = " ".join(f"p{n}: pullRequest(number: {n}) {{ number state headRefOid viewerDidAuthor "
                      f"labels(first: 20) {{ nodes {{ name }} }} }}" for n in numbers)
    query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
    found = json.loads(sh("gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}",
                          "-f", f"name={name}", repo=repo))["data"]["repository"]
    return {n: dict(found[f"p{n}"], repo=repo) for n in numbers}


def wait(repo, numbers, timeout):
    """Bumps the PRs whose current head has no result yet, then blocks until one of them settles and
    prints [{pr, head, status, fix?, ...}] for every listed PR that has. Settled = the reviewers are done
    with the head and, on my PR they posted on, a fix pass ran without pushing (its result is `fix`).
    Closed or merged counts as settled, a no-auto-review PR too. A held PR is not bumped, since a bump is
    a review request: it comes back as `held`."""
    state = load(repo)
    pending = [n for n, pr in heads(repo, numbers).items()
               if state.get(str(n), {}).get("sha") != pr["headRefOid"] and not state.get(str(n), {}).get("hold")
               and not unreviewed(pr)]
    save_bumped(repo, pending + [x for x in bumped(repo) if x not in pending])
    wake()
    deadline = time.monotonic() + timeout
    while True:
        state, fixes, now = load(repo), load(repo, FIXES), reviewing(repo)
        prs = heads(repo, numbers)
        skipped = {n for n, pr in prs.items() if unreviewed(pr)}
        reviewed = {n for n, pr in prs.items() if state.get(str(n), {}).get("sha") == pr["headRefOid"]} - skipped
        owed = {n for n in reviewed if fixing(prs[n], state, fixes)}
        fixed = {n: {k: v for k, v in fixes[str(n)].items() if k not in ("sha", "key")}
                 for n in reviewed - owed if fixes.get(str(n), {}).get("sha") == prs[n]["headRefOid"]}
        results = [{"pr": n, "head": pr["headRefOid"], "status": pr["state"].lower()} if pr["state"] != "OPEN"
                   else {"pr": n, "head": pr["headRefOid"], "status": NO_REVIEW} if n in skipped
                   else {"pr": n, "head": pr["headRefOid"], **state[str(n)], **({"fix": fixed[n]} if n in fixed else {})}
                   for n, pr in prs.items() if pr["state"] != "OPEN" or n in skipped | reviewed - owed]
        results = [{k: v for k, v in r.items() if k != "files"} for r in results]
        if results or time.monotonic() > deadline:
            return print(json.dumps(results or [{"pr": n, "head": pr["headRefOid"],
                                                 "status": ("fixing" if now[n].startswith("fix ") else "reviewing") if n in now
                                                 else "fix-queued" if n in owed else "queued"}
                                                for n, pr in prs.items()], indent=2))
        time.sleep(WAIT_POLL)


def reviewing(repo):
    """{pr: start time} of the repo's PRs that live runs review now."""
    prs = {}
    for live in glob(f"{path(repo, NOWS)}/*.json"):
        try:
            os.kill(int(os.path.basename(live)[:-5]), 0)
            prs |= {int(n): at for n, at in json.load(open(live)).items()}
        except (OSError, ValueError):
            pass
    return prs


def row(pr, seen, now, first, fixed={}):
    """(group, status, detail): 0 reviewing or fixing, 1 queued, 3 ready to approve, 4 idle."""
    requested = pr["requested"] or pr["number"] in first
    if requested and seen.get("status") == "baseline":
        seen = {}
    if pr["number"] in now:
        lane, _, at = now[pr["number"]].rpartition(" ")
        return 0, "fixing" if lane == "fix" else "reviewing", f"since {at}"
    if seen.get("sha") == pr["headRefOid"]:
        if ready(pr, seen, fixed):
            return 3, "ready", f"fix {fixed['status']}" if seen["status"] == "posted" and pr["viewerDidAuthor"] \
                else "quality notes only" if seen["verdict"] == "quality-only" else seen["at"]
        owed = seen["status"] == "posted" and pr["viewerDidAuthor"]
        detail = (f"fix {fixed['status']}" if fixed.get("sha") == pr["headRefOid"]
                  else NO_FIX if owed and labeled(pr, NO_FIX) else "fix queued" if owed else seen["at"])
        return 4, seen.get("verdict") or seen["status"], detail
    if unreviewed(pr):
        return 4, "skipped", NO_REVIEW
    if not seen and baselined(pr, requested):
        return 4, "new", "baseline on next run"
    if seen.get("hold") and not requested:
        return 4, "held", f"--next {pr['number']} to review"
    pushed = datetime.fromisoformat(pr["commits"]["nodes"][0]["commit"]["committedDate"]).astimezone()
    return 1, "queued", f"pushed {pushed:%a %H:%M}"


def bump(repo, n):
    state, now, prs = load(repo), reviewing(repo), queue()
    pr = next((p for p in prs if pr_key(p) == (repo, n) and not approved(p)), None)
    group, status, _ = row(pr, state.get(str(n), {}), now, [n]) if pr else (None, None, None)
    if group == 1:
        save_bumped(repo, [n] + [x for x in bumped(repo) if x != n])
        kick()
    else:
        print(f"#{n}: {'not in the queue' if not pr else 'already in review' if group == 0 else f'nothing new to review ({status})'}")
    show(prs)


def show(prs=None):
    tty, first = sys.stdout.isatty(), bumps()
    state, fixed = {r: load(r) for r in REPOS}, {r: load(r, FIXES) for r in REPOS}
    now = {r: reviewing(r) for r in REPOS}
    listed = ((*row(pr, state[pr["repo"]].get(str(pr["number"]), {}), now[pr["repo"]], first[pr["repo"]],
                    fixed[pr["repo"]].get(str(pr["number"]), {})), pr)
              for pr in prs or queue("--cache", LIST_CACHE))
    rows = sorted((r for r in listed if r[0] == 0 or not approved(r[3])),
                  key=lambda r: (r[0], priority(r[3], first), r[3]["number"] < max(now[r[3]["repo"]], default=0),
                                 r[3]["number"]))
    rank = 0
    for group, status, detail, pr in rows:
        rank += group == 1
        mark = {0: "▶", 1: str(rank), 3: "✓"}.get(group, "")
        name = f"{tag(pr['repo'])[1:]}#{pr['number']}"
        link = f"\033]8;;{url(*pr_key(pr))}\033\\{name}\033]8;;\033\\" if tty else name
        print(f"{mark:>2}  {link}  {status:<9}  {detail:<20}  {'[draft] ' * pr['isDraft']}{pr['title']}")


def worktrees(repo):
    """[(path, branch, head)] of every linked worktree; branch is None when detached."""
    trees = []
    for block in sh("git", "worktree", "list", "--porcelain", repo=repo).strip().split("\n\n")[1:]:
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        trees.append((fields["worktree"], fields.get("branch", "").removeprefix("refs/heads/") or None, fields["HEAD"]))
    return trees


def worktree_prs(repo, trees):
    """{path: [PR]}: the PRs whose head is the worktree's branch, else the PR that its name carries."""
    variables, fields = [], []
    for i, (path, branch, _) in enumerate(trees):
        if branch:
            variables.append((f"h{i}", "String", branch))
            fields.append(f"h{i}: pullRequests(headRefName: $h{i}, first: 10) {{ nodes {{ ...done }} }}")
        if m := PR_NUMBER.search(f"{branch} {os.path.basename(path)}"):
            variables.append((f"n{i}", "Int", m[1]))
            fields.append(f"n{i}: pullRequest(number: $n{i}) {{ ...done }}")
    owner, name = repo.split("/")
    query = (f"query($owner: String!, $name: String!{''.join(f', ${v}: {t}!' for v, t, _ in variables)}) "
             f"{{ repository(owner: $owner, name: $name) {{ {' '.join(fields)} }} }}" + WORKTREE_FRAGMENT)
    flags = [f for v, t, value in variables for f in ("-F" if t == "Int" else "-f", f"{v}={value}")]
    out = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}",
                          *flags], cwd=root(repo), capture_output=True, text=True, timeout=600)
    body = json.loads(out.stdout)
    if "data" not in body:
        log(repo, "-", f"prune skipped: {out.stderr.strip()[-200:]}")
        sys.exit(1)
    found = body["data"]["repository"]
    prs = lambda i: (found.get(f"h{i}") or {}).get("nodes") or [p for p in [found.get(f"n{i}")] if p]
    return {path: [dict(p, requested=any(r["requestedReviewer"].get("isViewer") for r in p["reviewRequests"]["nodes"]))
                   for p in prs(i)] for i, (path, *_) in enumerate(trees)}


def finished(prs):
    """Every PR still alive on the worktree's branch merged or carries my standing approval."""
    live = [p for p in prs if p["state"] != "CLOSED"]
    return bool(live) and all(p["state"] == "MERGED" or approved(p) for p in live)


def git_ok(repo, *args):
    return subprocess.run(["git", *args], cwd=root(repo), capture_output=True, timeout=600).returncode == 0


def pushed(repo, head, pr):
    """The worktree holds no commit beyond what the PR's head already has."""
    sha = pr["headRefOid"]
    if not git_ok(repo, "cat-file", "-e", f"{sha}^{{commit}}"):
        git_ok(repo, "fetch", "-q", "--no-tags", "origin", sha)
    return git_ok(repo, "merge-base", "--is-ancestor", head, sha)


def cwds():
    """The working directories of my running processes: a worktree under one is in use."""
    out = subprocess.run(["lsof", "-a", "-u", str(os.getuid()), "-d", "cwd", "-Fn"], capture_output=True, text=True)
    return [line[1:] for line in out.stdout.splitlines() if line.startswith("n")]


def blocker(repo, path, head, prs, busy):
    if any(d == path or d.startswith(f"{path}/") for d in busy):
        return "in use"
    if sh("git", "-C", path, "status", "--porcelain", repo=repo).strip():
        return "local changes"
    if not any(pushed(repo, head, pr) for pr in prs):
        return "unpushed commits"


def prune(repo, dry_run):
    """Removes the worktrees of PRs that merged or that I approved: nobody needs them locally anymore."""
    trees = worktrees(repo)
    prs, busy = worktree_prs(repo, trees), cwds()
    for path, _, head in trees:
        if not finished(prs[path]):
            continue
        n = prs[path][0]["number"]
        why = "merged" if all(p["state"] != "OPEN" for p in prs[path]) else "approved by me"
        if keep := blocker(repo, path, head, prs[path], busy):
            status = f"kept, {keep}"
        elif dry_run:
            status = "would be removed"
        else:
            status = "removed" if git_ok(repo, "worktree", "remove", path) else "remove failed"
        if dry_run or not keep:
            log(repo, n, f"worktree {status} ({why}): {path}")
    git_ok(repo, "worktree", "prune")


def prune_all(repos, dry_run):
    """One prune pass over `repos`. A repo that fails is logged and the next one still runs; True when any failed."""
    failed = False
    for repo in repos:
        try:
            prune(repo, dry_run)
        except SystemExit:
            failed = True
        except Exception as e:
            failed = True
            log(repo, "-", f"prune failed: {(getattr(e, 'stderr', None) or str(e)).strip()[-200:]}")
    return failed


def prune_forever(sleep=time.sleep):
    while True:
        prune_all(REPOS, False)
        sleep(PRUNE_EVERY)


def start_pruner():
    threading.Thread(target=prune_forever, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, help="review this PR now, even if its own diff is unchanged")
    ap.add_argument("-n", "--dry-run", action="store_true", help="print gate decisions, review nothing")
    ap.add_argument("-l", "--list", action="store_true", help="list the queue and each PR's last result")
    ap.add_argument("--next", type=int, metavar="PR", help="move this PR to the front of the review order")
    ap.add_argument("--wait", type=int, nargs="+", metavar="PR",
                    help="block until one of these PRs has a result for its current head, print it as JSON")
    ap.add_argument("--timeout", type=int, default=7200, help="seconds --wait blocks before it prints the pending state")
    ap.add_argument("--bg", action="store_true", help="refresh the daemon's queue now, or start the daemon")
    ap.add_argument("--daemon", action="store_true", help="review nonstop, refreshing the queue every 5 min")
    ap.add_argument("--prune", action="store_true",
                    help="remove the worktrees of PRs that merged or that I approved, in every repo")
    ap.add_argument("--repo", choices=REPOS, help="the repo of --pr, --next and --wait (default $IPR_REPO, "
                                                  f"else {MONOREPO}); --prune: only this repo")
    a = ap.parse_args()
    repo = a.repo or os.environ.get("IPR_REPO", MONOREPO)
    if a.list:
        return show()
    if a.next:
        return bump(repo, a.next)
    if a.wait:
        return wait(repo, a.wait, a.timeout)
    if a.daemon:
        return daemon()
    if a.prune:
        sys.exit(prune_all([a.repo] if a.repo else REPOS, a.dry_run))
    if a.bg:
        wake()
        return print(f"queue refresh requested — tail -f {LOG}")
    tick((repo, a.pr) if a.pr else None, a.dry_run)


if __name__ == "__main__":
    main()
