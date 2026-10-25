"""Reviews my own open PRs and the ones that wait on me, three at a time, then stays quiet until their own diff changes.

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

One process serves every project it detects: the repos of my PRs, of the PRs that request or are assigned to me,
and the config's projects, worked when a checkout under detect.roots (or the project's root) has them. The config
(~/.config/pr-wizard/config.json) sets each project's lanes, reviewers and gates; by default iprally/gitops gets the
fix lane alone. The daemon prunes the worktrees of every active project at start and every 30 min. pr_wizard/cli.py is the command line.

  my PR head ──▶ review (3) ──settled──▶ fix (3) ──pushed──▶ new head ─┐
       ▲                                    │ nothing pushed → stop     │
       └────────────────────────────────────────────────────────────────┘
Log: ~/Library/Logs/review-queue.log
"""
import fcntl, hashlib, json, os, re, signal, subprocess, sys, threading, time, traceback
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from pr_wizard import __version__, api, config, db, names, pools, projects, snapshot
from pr_wizard.names import (FIXES, LABEL, LOCK, LOG, MONOREPO, NO_FIX, NO_REVIEW, NOTIFIER, PID, PR_FIX, PR_REVIEW,
                              REPOS, STATE, env_repo, path, tag)

PR_NUMBER = re.compile(r"(?:fix|sync|review)-(\d{4,})")

PRUNE_EVERY = 1800
LIST_CACHE = "30s"
ATTEMPTS = 3
BACKOFF = (60, 180)
ROUNDS = config.DEFAULTS["review"]["rounds"]
WAIT_POLL = 30
READY = ("clean", "quality-only")
SETTLED = ("nothing-to-fix", "refuted-only", "no-changes")
LIMITED = object()
AT_LIMIT = re.compile(r"(?:\w+ and \w+ are )?both at their usage limit|\w+ is at its usage limit")
FALSE_CLEAN = re.compile(
    r"overloaded|api error|rate.?limit|no review (report|content)|not provided|^\(none\)$", re.I)

CLEAN_NOTICE = ("Automatic review pipeline ran on `{sha}`. None of the Opus code review, "
                "quality self-review or Codex code review found anything to fix. PR good to go.")

FRAGMENT = """
fragment pr on PullRequest {
  number title state isDraft headRefOid baseRefName additions deletions viewerDidAuthor mergeable updatedAt
  author { login }
  repository { nameWithOwner }
  labels(first: 20) { nodes { name } }
  latestOpinionatedReviews(first: 20) { nodes { state viewerDidAuthor } }
  commits(last: 1) { nodes { commit { committedDate statusCheckRollup {
    contexts(first: 0) { checkRunCountsByState { state count } } } } } }
  reviews { totalCount }
  reviewThreads(first: 100) { nodes { isResolved comments { totalCount } } }
}"""
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
NOTED = {}
CHECKOUTS = projects.Checkouts()


class Settings:
    """The config file as last read. It is read again when the file it resolves to changes."""

    def __init__(self):
        self.stamp, self.loaded = None, None

    def get(self):
        path = config.default_path()
        try:
            st = os.stat(path)
            stamp = path, os.path.realpath(path), st.st_mtime_ns, st.st_size
        except OSError:
            stamp = path, None
        if stamp != self.stamp:
            self.loaded, self.stamp = config.load(path), stamp
        return self.loaded


SETTINGS = Settings()


def cfg():
    return SETTINGS.get().config


def effective(repo, labels=()):
    return config.effective(cfg(), repo, labels=labels)


def lanes_of(pr):
    """The PR's effective config: its project's, with the labels applied."""
    return effective(pr["repo"], [l["name"] for l in pr["labels"]["nodes"]])


def reviewers(repo):
    return [r["id"] for r in effective(repo)["review"]["reviewers"] if r.get("enabled", True)]


def found(wanted=()):
    return CHECKOUTS.get(cfg(), wanted)


def checkouts():
    """{repo: path} of every local checkout: the scan of detect.roots, with the config's roots over it."""
    return {repo: where["path"] for repo, where in found().items() if "path" in where}


def listed(prs):
    """Every project of the fetch and the config, with its status (api.md §3.2 `projects[]`)."""
    return projects.listing(prs, cfg(), found())


def active(prs):
    return [p["repo"] for p in listed(prs) if p["status"] == "active"]


def root(repo):
    return checkouts()[repo]


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


def announce(type, pr, verdict=None):
    """Records a `ready_for_approval` or `ready_withdrawn` event for the API (api.md §3.3). UIs notify from it."""
    db.add_event(type, pr["repo"], pr["number"], pr["title"], url(pr["repo"], pr["number"]),
                 (pr["author"] or {}).get("login", "ghost"), pr["headRefOid"], verdict)


def review_notifier(repo, pr, *args):
    out = subprocess.run([NOTIFIER, "-group", f"review-queue{tag(repo)}-{pr}", *args], capture_output=True, text=True)
    if out.returncode:
        log(repo, pr, f"Review Queue notifier failed: {(out.stderr or out.stdout).strip()}")


def sh(*args, repo=MONOREPO):
    return subprocess.run(args, cwd=repo and root(repo), capture_output=True, text=True,
                          timeout=600, check=True).stdout


def load(repo, kind=STATE):
    return {str(n): e for n, e in (db.reviews if kind == STATE else db.fixes)(repo).items()}


def paused():
    return db.meta_get("paused") == "1"


def bumped(repo):
    return db.next_list(repo)


def bumps():
    first = {}
    for key in db.next_keys():
        repo, n = key.rsplit("#", 1)
        first.setdefault(repo, []).append(int(n))
    return first


def save_bumped(repo, prs):
    with db.tx():
        for n in set(bumped(repo)) - set(prs):
            db.drop_next(repo, n)
        db.bump(repo, *prs)


def priority(pr, first):
    """Bumped PRs first, then mine, then the rest."""
    mine = first.get(pr["repo"], [])
    return pr["number"] not in mine, mine.index(pr["number"]) if pr["number"] in mine else 0, not pr["viewerDidAuthor"]


def tagged(pr, requested):
    return dict(pr, repo=pr["repository"]["nameWithOwner"], requested=requested)


def pr_of(repo, n):
    owner, name = repo.split("/")
    pr = json.loads(sh("gh", "api", "graphql", "-f", f"query={PR_QUERY}", "-f", f"owner={owner}",
                       "-f", f"name={name}", "-F", f"number={n}", repo=repo))["data"]["repository"]["pullRequest"]
    return [tagged(pr, True)] if pr["state"] == "OPEN" else []


def graphql(*flags):
    return lambda query, variables: json.loads(sh("gh", "api", "graphql", *flags, "-f", f"query={query}",
                                                  *(f for k, v in variables.items() for f in ("-f", f"{k}={v}")),
                                                  repo=None))["data"]


def fetched(*flags, note=lambda _: None):
    """(PRs, points spent, points left): my own PRs, review requests and PRs assigned to me (drafts too), plus PRs
    I reviewed before, since a posted review drops the request, in any repo. A colleague's PR assigned to me counts
    as a review request until my approval stands, since an assignment, unlike a request, outlives my review.
    `flags` go to the `gh api` calls."""
    searches, cost, left = projects.fetch(graphql(*flags), FRAGMENT, note)
    hits = {alias: [tagged(p, False) for p in nodes] for alias, nodes in searches.items()}
    assigned = [p for p in hits["assigned"] if not p["viewerDidAuthor"] and not approved_by_me(p)]
    requested = {pr_key(p) for p in hits["requested"] + assigned}
    prs = {pr_key(p): p for alias in ("reviewed", "assigned", "requested", "mine") for p in hits[alias]}
    return [dict(p, requested=k in requested) for k, p in sorted(prs.items())], cost, left


def queue(*flags):
    return fetched(*flags)[0]


def approved_by_me(pr):
    return any(r["viewerDidAuthor"] and r["state"] == "APPROVED" for r in pr["latestOpinionatedReviews"]["nodes"])


def approved(pr):
    """My approval stands and nobody re-requested my review since."""
    return not pr["requested"] and approved_by_me(pr)


def labeled(pr, label):
    return any(l["name"] == label for l in pr["labels"]["nodes"])


def unreviewed(pr):
    return pr["repo"] not in checkouts() or not lanes_of(pr)["review"]["enabled"]


def unfixed(pr):
    return pr["repo"] not in checkouts() or not lanes_of(pr)["fix"]["enabled"]


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


def progress(repo, pr, reviewer, state, attempt):
    """Sets one reviewer's step in the PR's `runs` row, in the project's reviewer order."""
    with db.tx():
        steps = {s["id"]: s for s in db.live_runs(repo)[pr]["reviewers"]}
        steps[reviewer] = {"id": reviewer, "state": state, "attempt": attempt, "since": db.now()}
        db.run_update(repo, pr, [steps[r] for r in reviewers(repo) if r in steps])


def run_reviewer(repo, pr, reviewer):
    force = []
    for i in range(ATTEMPTS):
        if i:
            progress(repo, pr, reviewer, "waiting", i + 1)
            log(repo, pr, f"{reviewer} retry in {BACKOFF[i - 1]} s")
            time.sleep(BACKOFF[i - 1])
        progress(repo, pr, reviewer, "running", i + 1)
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
            progress(repo, pr, reviewer, "clean" if res.get("stop") else "posted", i + 1)
            return res
        if limit := AT_LIMIT.search(out.stderr):
            log(repo, pr, f"{reviewer} stopped: {limit[0]}")
            progress(repo, pr, reviewer, "limited", i + 1)
            return LIMITED
        force = force or (["--force"] if res and false_clean(res) else [])
        why = (out.stderr.strip() or out.stdout.strip())[-300:].replace("\n", " ⏎ ")
        log(repo, pr, f"{reviewer} attempt {i + 1}/{ATTEMPTS} failed: {why}")
    progress(repo, pr, reviewer, "failed", ATTEMPTS)


def outcome(res):
    if res.get("posted"):
        return f"posted {res.get('findings')} finding(s), {res.get('inline')} inline — {res.get('url')}"
    return f"{res.get('skipped') or res.get('reason')} — {(res.get('summary') or res.get('message') or '').strip()[:160]}"


def reviewer_result(res):
    """The `reviewer_results` row of a finished run. A run skipped as already reviewed has no digest: its stored
    row stays. One skipped for lack of conventions stores a `skipped` row."""
    conventions = res.get("conventions")
    if res.get("reason") == "no-conventions":
        return {"result": "skipped", "round": res.get("round"), "conventions": conventions}
    if "digest" not in res:
        return None
    result = "clean" if res.get("reason") == "no-findings" else "notes-only" if res.get("stop") else "posted"
    return {"result": result, "engine": res.get("engine"), "round": res.get("round"), "digest": res["digest"],
            "conventions": conventions, "url": res.get("url")}


def review(repo, pr, sha):
    ids = reviewers(repo)
    if not ids:
        return "skipped", "no reviewer enabled"
    with ThreadPoolExecutor(len(ids)) as pool:
        results = dict(zip(ids, pool.map(lambda r: run_reviewer(repo, pr, r), ids)))
    for reviewer, res in results.items():
        if res and res is not LIMITED and (row := reviewer_result(res)):
            db.put_reviewer_result(repo, pr, sha, reviewer, row)
    limited = [r for r, res in results.items() if res is LIMITED]
    if limited:
        return "limited", f"{', '.join(limited)} hit the usage limit"
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
    gate = effective(pr["repo"])["review"]
    if seen and all(any(fnmatch(f, g) for g in gate["trivial"]) for f in changed):
        return "trivial", f"only trivial files: {', '.join(sorted(changed))}"
    if seen.get("hold") and not pr["requested"]:
        return "held", f"clean before, review only on request: --next {pr['number']} or --pr {pr['number']}"
    if seen.get("rounds", 0) >= gate["rounds"]:
        return "needs-human", f"{gate['rounds']} rounds in a row with findings, review it by hand or run --pr {pr['number']}"
    if pr["additions"] > gate["max_added"]:
        return "too-big", f"{pr['additions']} added lines, review it by hand"


def log_once(repo, n, msg):
    """Log a skip once per reason, not on every refresh."""
    if NOTED.get((repo, n)) != msg:
        NOTED[repo, n] = msg
        log(repo, n, msg)


def in_review(repo, n, on, lane="review"):
    db.run_start(repo, n, lane, reviewers=[] if lane == "review" else None) if on else db.run_end(repo, n)


def record(repo, key, entry, kind=STATE):
    (db.put_review if kind == STATE else db.put_fix)(repo, key, entry)


@contextmanager
def claimed(repo, n):
    """True while this process holds PR n; a second run skips it instead of reviewing it twice."""
    os.makedirs(os.path.dirname(names.lock(repo, n)), exist_ok=True)
    with open(names.lock(repo, n), "w") as fh:
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
        if seen.get("verdict") in READY and not pr["viewerDidAuthor"]:
            announce("ready_withdrawn", pr)
        in_review(repo, n, True)
        try:
            status, note = review(repo, n, pr["headRefOid"])
        finally:
            in_review(repo, n, False)
    log(repo, n, f"{status}: {note}" + (", retrying on the next refresh" if status == "limited" else ""))
    advisory = {r["id"] for r in effective(repo)["review"]["reviewers"] if r.get("advisory")}
    verdict = {"clean": "clean", "posted": "quality-only" if set(note.split(", ")) <= advisory else "posted"}.get(
        status, seen.get("verdict") if status in ("unchanged", "trivial", "limited") else None)
    if status == "clean":
        post_clean_notice(repo, n, pr["headRefOid"])
    if status in ("clean", "posted") and verdict in READY and not pr["viewerDidAuthor"]:
        ready_alert(repo, n, pr["title"])
        announce("ready_for_approval", pr, verdict)
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
    return (pr["viewerDidAuthor"] and not unfixed(pr) and reviewed
            and fixes.get(str(pr["number"]), {}).get("key") != feedback_key(pr))


def fixing(pr, state, fixes):
    """The fix lane still owes this head a pass: the reviewers posted and no pass ran on it yet, or
    the last one errored or went red and will run again."""
    fixed = fixes.get(str(pr["number"]), {})
    return (pr["viewerDidAuthor"] and not unfixed(pr)
            and state.get(str(pr["number"]), {}).get("status") == "posted"
            and (fixed.get("sha") != pr["headRefOid"] or not fixed.get("key")))


def ready(pr, seen, fixed):
    """Clean for good: a clean review, or a fix pass on my posted head that left nothing to push. On my PR,
    a fix pass on the head that did not settle (red CI it could not land a fix for) overrides a clean review."""
    if pr["viewerDidAuthor"] and (seen.get("status") == "posted" or fixed.get("sha") == pr["headRefOid"]):
        return fixed.get("sha") == pr["headRefOid"] and fixed.get("status") in SETTLED
    return seen.get("verdict") in READY


def fix_note(res, err, repo=MONOREPO):
    status = res.get("status", "error")
    if status == "pushed":
        merged = "merged the base, " if res.get("merged") else ""
        return f"pushed {res['pushed'][:12]}: {merged}{res['fixed']} fixed, {res['refuted']} refuted, {res['deferred']} deferred"
    if status == "tests-red":
        gate = res.get("gate") or ", ".join(g["name"] for g in effective(repo)["fix"]["gates"] if g["kind"] == "test")
        return f"{gate} red in {', '.join(res['failing'])} — {res['worktree']}"
    if status == "error":
        return (err.strip().splitlines() or ["pr_fix.py printed nothing"])[-1][-200:]
    return (res.get("summary") or status).strip()[:160]


def fix(pr, first):
    repo, n, head = pr["repo"], pr["number"], pr["headRefOid"]
    log(repo, n, f"fixing {head[:12]}: {pr['title']}")
    knobs = effective(repo)["fix"]
    in_review(repo, n, True, "fix")
    try:
        out = subprocess.run([sys.executable, PR_FIX, "run", "--pr", str(n)], **child(repo), capture_output=True,
                             text=True, timeout=knobs["pass_timeout_s"])
    finally:
        in_review(repo, n, False)
    try:
        res = json.loads(out.stdout)
    except ValueError:
        res = {}
    status, note = res.get("status", "error"), fix_note(res, out.stderr, repo)
    log(repo, n, f"fix {status}: {note}" + (", retrying on the next refresh" if status == "limited" else ""))
    if status == "limited":
        return
    errors = load(repo, FIXES).get(str(n), {}).get("errors", 0) + 1 if status in ("error", "tests-red") else 0
    record(repo, str(n), {"sha": head, "key": feedback_key(pr) if not errors or errors >= knobs["max_errors"] else None,
                          "status": status, "note": note, "errors": errors, "at": f"{datetime.now():%F %T}"}, FIXES)
    if status == "pushed":
        kick()


class Pending:
    """The PRs from the latest queue fetch that no worker has taken yet, keyed by (repo, number). Pools that share
    `cond` and `held` never hand out a PR another of them runs."""

    def __init__(self, prs=(), workers=0, cond=None, held=None):
        self.prs, self.busy, self.workers, self.live = list(prs), set(), workers, 0
        self.cond, self.held, self.paused = cond or threading.Condition(), self.busy if held is None else held, False

    def pause(self, on):
        """A paused pool hands out no PR. Running passes finish."""
        with self.cond:
            self.paused = on
            self.cond.notify_all()

    def resize(self, workers, spawn):
        """Starts the missing workers through `spawn` at once and returns them. A worker over the size retires
        when it next looks for work, so no pass is cut short."""
        with self.cond:
            self.workers, grow = workers, max(workers - self.live, 0)
            self.live += grow
            self.cond.notify_all()
        return [spawn() for _ in range(grow)]

    def refill(self, prs):
        with self.cond:
            self.prs = [pr for pr in prs if pr_key(pr) not in self.held]
            self.cond.notify_all()

    def take(self, wait):
        with self.cond:
            while not self.free() or self.live > self.workers or self.paused:
                if self.live > self.workers or not wait:
                    return None
                self.cond.wait()
            first = bumps()
            pr = min(self.prs, key=lambda p: priority(p, first))
            self.prs.remove(pr)
            self.busy.add(pr_key(pr))
            self.held.add(pr_key(pr))
            return pr, first.get(pr["repo"], [])

    def free(self):
        self.prs = [pr for pr in self.prs if pr_key(pr) not in self.held]
        return self.prs

    def done(self, key):
        with self.cond:
            self.busy.discard(key)
            self.held.discard(key)

    def retire(self):
        with self.cond:
            self.live -= 1

    def idle(self):
        with self.cond:
            return not self.prs and len(self.busy) < self.workers


def work(pending, wait, job):
    try:
        while True:
            try:
                picked = pending.take(wait)
            except Exception:
                say(f"worker could not take a PR: {traceback.format_exc().strip()[-300:]}".replace("\n", " ⏎ "))
                time.sleep(1)
                continue
            if not picked:
                return
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
    finally:
        pending.retire()


def worker(pending, wait, job):
    thread = threading.Thread(target=work, args=(pending, wait, job), daemon=True)
    thread.start()
    return thread


def run(pending, wait, job):
    for thread in pending.resize(pending.workers, lambda: worker(pending, wait, job)):
        thread.join()


def reviewer(only, dry_run):
    return lambda pr, first: handle(pr, first, only, dry_run)


def tick(only, dry_run):
    """`only` is (repo, number): review that PR now."""
    started = time.monotonic()
    pending = Pending(pr_of(*only) if only else [pr for pr in queue() if pr["repo"] in checkouts()],
                      cfg()["review"]["workers"])
    say(f"tick started{' (dry run)' if dry_run else ''}: {len(pending.prs)} PR(s) in queue")
    if only and not pending.prs:
        log(*only, "not an open PR")
    run(pending, False, reviewer(only, dry_run))
    say(f"tick done in {time.monotonic() - started:.0f} s")


def review_now(repo, n):
    """`--pr n` in a thread of the daemon, beside its pools."""
    try:
        tick((repo, n), False)
    except Exception as e:
        log(repo, n, f"review now failed: {(getattr(e, 'stderr', None) or str(e)).strip()[-200:]}")


def lanes(project):
    return "+".join(lane for lane in ("review", "fix") if project[lane]) if project["status"] == "active" \
        else project["status"]


def summary(listing):
    return ", ".join(f"{p['repo']} {lanes(p)}" for p in listing)


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
    return {repo for repo in checkouts() if repo == MONOREPO or repo in held or repo not in REPOS}


class Runtime:
    """What the API serves: the last queue fetch, its refresh status, and the changes long-polls wait on."""

    def __init__(self):
        self.prs, self.fetched_at, self.refresh = [], None, {"last_at": None, "last_error": None}
        self.started, self.started_at, self.changes = time.time(), db.now(), api.Changes()
        self.refresh_now, self.pools = threading.Event(), None
        self.commit = subprocess.run(["git", "-C", names.ROOT, "rev-parse", "--short", "HEAD"],
                                     capture_output=True, text=True).stdout.strip() or None

    @property
    def cfg(self):
        return SETTINGS.get()

    def apply(self):
        """Builds the pools the config asks for over the last fetch's projects, live."""
        self.pools.apply(self.cfg.config, listed(self.prs))
        if NOTED.get("pools") != (line := "pools: " + ", ".join(f"{k} ×{n}" for k, n in self.pools.sizes().items())):
            NOTED["pools"] = line
            say(line)

    def attach(self, pools):
        """The daemon's pools, which config writes rebuild and pause stops. They start paused when the db says so."""
        self.pools = pools
        pools.pause(paused())
        if paused():
            say("paused: workers take no new PR until POST /v1/resume")

    def refetch(self):
        self.refresh_now.set()

    def save_config(self, doc):
        """Saves through the symlink, then applies at once: the pools resize and the queue refetches."""
        config.save(doc)
        SETTINGS.stamp = None
        if self.pools:
            self.apply()
        self.refetch()
        self.changes.touch()
        say(f"config saved: rev {config.rev(doc)}")
        return self.config()

    def bump(self, prs, only_queued):
        """api.md §3.9: the PRs that may go first move to the front in one transaction, then the queue refetches."""
        known, runs = {pr_key(p): p for p in self.prs}, db.live_runs()
        repos = self.repos()
        why = [unbumpable(repo, n, known.get((repo, n)), runs, repos) if only_queued or repo not in repos
               else None for repo, n in prs]
        go = [pr for pr, reason in zip(prs, why) if reason is None]
        if go:
            with db.tx():
                for repo, n in reversed(go):
                    db.bump(repo, n)
            self.refetch()
        return {"next": db.next_keys(), "results": [{"key": f"{repo}#{n}", "bumped": reason is None, "reason": reason}
                                                    for (repo, n), reason in zip(prs, why)]}

    def review(self, repo, n):
        """api.md §3.10: `--pr n` past every gate and label, but not past the config."""
        self.known(repo)
        if repo not in checkouts():
            raise api.Problem(409, "no_checkout", f"{repo} has no local checkout, set projects[{repo}].root")
        if not effective(repo)["review"]["enabled"]:
            raise api.Problem(409, "review_lane_off", f"the review lane of {repo} is off")
        idle(repo, n)
        threading.Thread(target=review_now, args=(repo, n), daemon=True).start()

    def fix(self, repo, n):
        """api.md §3.11: re-arms the PR's fix pass, so the next refresh queues one."""
        self.known(repo)
        pr = next((p for p in self.prs if pr_key(p) == (repo, n)), None)
        if not pr:
            raise api.Problem(404, "not_in_queue", f"{repo}#{n} is not in the last queue fetch")
        if not pr["viewerDidAuthor"]:
            raise api.Problem(409, "not_mine", f"{repo}#{n} is not my PR")
        if labeled(pr, NO_FIX):
            raise api.Problem(409, "no_auto_fix", f"{repo}#{n} is labeled {NO_FIX}")
        if unfixed(pr):
            raise api.Problem(409, "fix_lane_off", f"the fix lane of {repo} is off")
        idle(repo, n)
        db.rearm_fix(repo, n)
        self.refetch()

    def pause(self, on):
        db.meta_set("paused", int(on))
        self.pools.pause(on)
        say("paused: workers take no new PR" if on else "resumed")
        return on

    def refreshed(self, prs=None, error=None):
        at = db.now()
        if error is None:
            self.prs, self.fetched_at = prs, at
        self.refresh = {"last_at": at, "last_error": error}
        self.changes.touch()

    def repos(self):
        return projects.repos(cfg(), self.prs)

    def known(self, repo):
        if repo not in self.repos():
            raise api.Problem(404, "unknown_repo", f"{repo} is not a known project")

    def events(self, since):
        return db.events_after(since)

    def snapshot(self):
        return snapshot.build(self.prs, snapshot.read(self.prs), {"generated_at": db.now(), "fetched_at": self.fetched_at,
                                                          "paused": paused(), "refresh": self.refresh})

    def info(self):
        snap, loaded = self.snapshot(), self.cfg
        return {"name": "pr-wizard", "version": __version__, "commit": self.commit, "api": 1, "pid": os.getpid(),
                "started_at": self.started_at, "uptime_s": int(time.time() - self.started), "label": LABEL,
                "paused": snap["paused"], "projects": snap["projects"], "lanes": snap["lanes"],
                "refresh": {**loaded.config["refresh"], **snap["refresh"]},
                "config": {"path": loaded.path, "real_path": loaded.real_path, "rev": loaded.rev, "error": loaded.error},
                "paths": {"socket": names.SOCKET, "state": names.WIZARD, "db": db.DB, "log": LOG}}

    def config(self):
        loaded, listing = self.cfg, self.snapshot()["projects"]
        return {"rev": loaded.rev, "path": loaded.path, "real_path": loaded.real_path, "source": loaded.source,
                "error": loaded.error, "config": loaded.config, "defaults": config.DEFAULTS,
                "effective": {p["repo"]: {"root": p["checkout"] and p["checkout"]["path"],
                                          **config.effective(loaded.config, p["repo"])} for p in listing},
                "choices": config.choices()}


def idle(repo, n):
    if n in db.live_runs(repo):
        raise api.Problem(409, "busy", f"a live run already holds {repo}#{n}")


def unbumpable(repo, n, pr, runs, repos):
    """Why `--next` leaves the PR where it is, or None to bump it. A bump is a review request."""
    if repo not in repos:
        return "unknown-repo"
    if not pr or approved(pr):
        return "not-in-queue"
    if unreviewed(pr):
        return "review-lane-off"
    if (repo, n) in runs:
        return "active"
    return None if row(pr, db.review(repo, n), {}, [n], db.fix(repo, n))[0] == 1 else "nothing-new"


def serve(rt):
    """The API thread on the one socket, in the 0700 state dir. SIGTERM unlinks the socket and exits at once: running passes do not hold it."""
    os.makedirs(names.WIZARD, exist_ok=True)
    os.chmod(names.WIZARD, 0o700)
    server = api.bind(rt, names.SOCKET)
    signal.signal(signal.SIGTERM, lambda *_: (Path(names.SOCKET).unlink(missing_ok=True), os._exit(143)))
    names.write_label()
    db.COMMITS.append(rt.changes.touch)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=api.watch, args=(rt.changes, threading.Event()), daemon=True).start()
    say(f"api on {names.SOCKET}")
    return server


def daemon():
    """Workers review nonstop. The queue data behind them refreshes every `refresh.interval_s`, every
    `refresh.idle_s` while a worker has nothing to take, and at once on SIGUSR1. Each refresh builds the pools
    the config asks for."""
    lock = open(path(MONOREPO, LOCK), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return say("daemon already running")
    with open(path(MONOREPO, PID), "w") as fh:
        fh.write(str(os.getpid()))
    db.sweep_runs()
    rt = Runtime()
    serve(rt)
    held = {}
    rt.attach(pools.Pools())
    signal.signal(signal.SIGUSR1, lambda *_: rt.refetch())

    def refresh():
        idle = False
        while True:
            started, every = time.monotonic(), cfg()["refresh"]
            try:
                prs, cost, left = fetched(note=say)
                found({pr["repo"] for pr in prs})
                served = serving(held)
                worked = [pr for pr in prs if pr["repo"] in served]
                rt.refreshed(prs)
                rt.apply()
                rt.pools.refill("review", worked)
                state, fixed = {r: load(r) for r in served}, {r: load(r, FIXES) for r in served}
                rt.pools.refill("fix", [pr for pr in worked if fixable(pr, state[pr["repo"]], fixed[pr["repo"]])])
                if NOTED.get("projects") != (line := f"projects: {summary(listed(prs))}"):
                    NOTED["projects"] = line
                    say(line)
                if not idle:
                    say(f"queue refreshed: {len(prs)} PR(s), {sum(len(p.busy) for p, _ in rt.pools.of('review'))} in review, "
                         f"{sum(len(p.prs) + len(p.busy) for p, _ in rt.pools.of('fix'))} to fix, search cost {cost} points ({left} left)")
            except Exception as e:
                error = (getattr(e, 'stderr', None) or str(e)).strip()[-200:]
                say(f"queue refresh failed: {error}")
                rt.refreshed(error=error)
            idle = False
            while not rt.refresh_now.wait(every["idle_s"]):
                if time.monotonic() - started >= every["interval_s"]:
                    break
                if rt.pools.idle():
                    idle = True
                    break
            rt.refresh_now.clear()

    knobs = cfg()
    say(f"daemon started: {summary(listed([]))}")
    say(f"queue refresh every "
         f"{knobs['refresh']['interval_s'] // 60} min, every {knobs['refresh']['idle_s']} s while a review worker is idle")
    start_pruner(lambda: active(rt.prs))
    rt.apply()
    refresh()


def kick():
    """Ask the daemon for a queue refresh now; False when no daemon runs."""
    try:
        os.kill(int(open(path(MONOREPO, PID)).read()), signal.SIGUSR1)
        return True
    except (OSError, ValueError):
        return False


def heads(repo, numbers):
    """{pr: {repo, number, state, headRefOid, viewerDidAuthor, labels}} in one GraphQL call."""
    owner, name = repo.split("/")
    fields = " ".join(f"p{n}: pullRequest(number: {n}) {{ number state headRefOid viewerDidAuthor "
                      f"labels(first: 20) {{ nodes {{ name }} }} }}" for n in numbers)
    query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
    found = json.loads(sh("gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}",
                          "-f", f"name={name}", repo=repo))["data"]["repository"]
    return {n: dict(found[f"p{n}"], repo=repo) for n in numbers}


def unsettled(repo, numbers):
    """The PRs `--wait` bumps: their current head has no result yet. A held PR is not bumped, since a bump is a
    review request: it comes back as `held`."""
    state = load(repo)
    return [n for n, pr in heads(repo, numbers).items()
            if state.get(str(n), {}).get("sha") != pr["headRefOid"] and not state.get(str(n), {}).get("hold")
            and not unreviewed(pr)]


def settle(repo, numbers, timeout):
    """Blocks until one of the PRs settles and prints [{pr, head, status, fix?, ...}] for every listed PR that has.
    Settled = the reviewers are done with the head and, on my PR they posted on, a fix pass ran without pushing
    (its result is `fix`). Closed or merged counts as settled, a no-auto-review PR too."""
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
    """{pr: "<lane> HH:MM:SS"} of the repo's PRs that live runs review or fix now."""
    return {n: f"{r['lane']} {r['since'][11:19]}" for n, r in db.live_runs(repo).items()}


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
                  else NO_FIX if owed and labeled(pr, NO_FIX) else "fix lane off" if owed and unfixed(pr)
                  else "fix queued" if owed else seen["at"])
        return 4, seen.get("verdict") or seen["status"], detail
    if pr["repo"] not in checkouts():
        return 4, "skipped", "no checkout"
    if not effective(pr["repo"])["review"]["enabled"] and not effective(pr["repo"])["fix"]["enabled"]:
        return 4, "skipped", "lanes off"
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
    prs, at = prs or queue("--cache", LIST_CACHE), db.now()
    runtime = {"generated_at": at, "fetched_at": at, "paused": paused(), "refresh": {"last_at": at, "last_error": None}}
    print(snapshot.render(snapshot.build(prs, snapshot.read(prs), runtime), sys.stdout.isatty()), end="")


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
    if not os.path.isdir(path):
        return None
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


def prune_forever(repos, sleep=time.sleep):
    while True:
        prune_all(repos(), False)
        sleep(PRUNE_EVERY)


def start_pruner(repos):
    threading.Thread(target=prune_forever, args=(repos,), daemon=True).start()


def migrated(done, dry_run):
    if not done:
        return "state.db already holds the imported state"
    rows = "\n".join(f"  {repo:<16} " + "  ".join(f"{t} {n}" for t, n in tables.items())
                     for repo, tables in done["rows"].items())
    return (f"{'would import' if dry_run else 'imported'}:\n{rows}\n{len(done['files'])} files to legacy/, "
            f"{len(done['scratch'])} scratch dirs to scratch/, {len(done['ephemera'])} locks and live-run files deleted")
