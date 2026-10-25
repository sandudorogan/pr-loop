#!/usr/bin/env python3
"""One fix pass on a PR: headless Codex fixes the open review feedback, this script lands it.

Usage:
  pr_fix.py run  --pr N    fix, format, test, commit, push, then 👍 + resolve, or reply + resolve
  pr_fix.py dump --pr N    print the feedback the next run would hand to Codex

Codex runs sandboxed (workspace-write, no network) and never touches git, so every step that
needs git writes, the network or a browser happens here:

  feedback ──▶ codex (one session per PR, resumed) ──▶ format gates ──▶ test gates per item
                    ▲                                                          │ red
                    └──────────────── failure output, at most 2× ◀─────────────┘
                                                                               │ green
                    👍 + resolve fixed · reply to refuted ◀── commit + push

Feedback is every unresolved review thread whose last word is not mine, plus the review bodies
left on the current head, minus notes-only reviews (`<!-- agent-review-fyi -->`), plus every failed
Actions job on the head with the tail of its log, even while the rest of its run goes on. A job
Codex refutes gets a fresh run: the base merged in when it moved, else a rerun, by a later pass when
its run has not finished yet (GitHub refuses a rerun before). A rerun is a new job, so one still red
comes back to Codex with the earlier refutations, CI_TRIES looks in a row at most; after that the job
waits for a human. A conflict with the base is merged first, as its own commit, with Codex resolving
the markers. Prints one JSON result whose `status` is pushed | refuted-only | no-changes |
nothing-to-fix | ci-stuck | tests-red | limited. A tests-red pass leaves its work in the worktree;
the next pass on the same head tests it again and carries on from there, and a new head discards it.
Any other local change (a pass that died mid-way) is stashed, never lost.
"""
import argparse, fcntl, json, os, re, shutil, subprocess, sys, tempfile

DIR = os.path.dirname(os.path.realpath(__file__))
sys.path[:0] = [DIR, os.path.dirname(DIR)]
from pr_review import CFG, LIMIT, LOADED, REPO, REPO_ROOT, brief, codex_flags
from pr_wizard import config, conventions, db, gates, names

SCHEMA = os.path.join(DIR, "fix-schema.json")
AGENT_MARKER = "<!-- agent-review:"
FYI_MARKER = "<!-- agent-review-fyi -->"
CI_LOG_CHARS = 20000
LOG_NOISE = re.compile(r"^﻿?\d{4}-\d\d-\d\dT\S+Z |\x1b\[[0-9;]*m", re.M)
ATTRIBUTION = re.compile(r"^(co-authored-by:|.*generated with \[?claude)", re.I | re.M)


def configure(cfg):
    """Sets the fixer config a pass works with: the project's at import, the PR's once `--pr` is known."""
    global FIX, PROMPT, MERGE_PROMPT, TIMEOUT, TEST_RETRIES, GATES, CI_TRIES
    FIX = cfg["fix"]
    PROMPT, MERGE_PROMPT = (os.path.join(DIR, "prompts", FIX[k]) for k in ("prompt", "merge_prompt"))
    TIMEOUT, TEST_RETRIES, GATES, CI_TRIES = FIX["turn_timeout_s"], FIX["test_retries"], FIX["gates"], FIX["ci_tries"]


configure(CFG)

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviewThreads(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { id isResolved isOutdated path line
              comments(first: 50) { nodes { databaseId author { login } body } } } } } }
}"""
RESOLVE = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sh(args, cwd=REPO_ROOT, timeout=600, check=True):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if check and out.returncode:
        die(f"{' '.join(args[:4])}… exited {out.returncode}\n{(out.stderr or out.stdout).strip()[-2000:]}")
    return out.stdout


def gh(*args):
    return json.loads(sh(["gh", "api", *args]) or "null")


def load(pr):
    return db.fix_state(REPO, pr)


def save(pr, state):
    db.put_fix_state(REPO, pr, state)


# ---------------------------------------------------------------- feedback

def threads(pr):
    owner, name = REPO.split("/")
    nodes, cursor = [], None
    while True:
        page = gh("graphql", "-f", f"query={THREADS_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}",
                  "-F", f"number={pr}", *(["-f", f"cursor={cursor}"] if cursor else []))
        conn = page["data"]["repository"]["pullRequest"]["reviewThreads"]
        nodes += conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


def login(c):
    return (c.get("author") or c.get("user") or {}).get("login", "ghost")


def mine_last(comments, me):
    """My own reply without an agent marker ends the thread: a refutation already posted."""
    last = comments[-1]
    return login(last) == me and AGENT_MARKER not in (last["body"] or "")


def feedback(pr, head, state):
    """Deferred threads come back only when someone adds a comment; handled review bodies never do."""
    me = sh(["gh", "api", "user", "--jq", ".login"]).strip()
    deferred, handled = state.get("deferred", {}), state.get("handled_reviews", [])
    items = []
    for t in threads(pr):
        comments = t["comments"]["nodes"]
        if (t["isResolved"] or not comments or FYI_MARKER in comments[0]["body"] or mine_last(comments, me)
                or deferred.get(t["id"]) == len(comments)):
            continue
        items.append({"ref": t["id"], "kind": "thread", "path": t["path"], "line": t["line"],
                      "outdated": t["isOutdated"], "top": comments[0]["databaseId"], "count": len(comments),
                      "comments": [{"author": login(c), "body": c["body"]} for c in comments]})
    for r in (r for page in gh(f"repos/{REPO}/pulls/{pr}/reviews?per_page=100", "--paginate", "--slurp") for r in page):
        body = r.get("body") or ""
        if (r["commit_id"] == head and body.strip() and FYI_MARKER not in body and r["id"] not in handled
                and (login(r) != me or AGENT_MARKER in body)):
            items.append({"ref": f"review:{r['id']}", "kind": "review", "author": login(r), "body": body,
                          "url": r["html_url"], "id": r["id"]})
    return items


def checks(head):
    """The latest job per name on the head from the `fix.ci_apps` apps; a rerun replaces its job."""
    runs = gh(f"repos/{REPO}/commits/{head}/check-runs?per_page=100", "--paginate", "--slurp")
    return [c for page in runs for c in page["check_runs"] if c["app"]["slug"] in FIX["ci_apps"]]


def failed(c):
    return c["conclusion"] in ("failure", "timed_out")


def stuck(jobs, state):
    return [c["name"] for c in jobs if failed(c) and len(state.get("ci_tries", {}).get(c["name"], [])) >= CI_TRIES]


def failed_jobs(jobs, state):
    """Failed jobs no pass has looked at, each with the tail of its log and the earlier refutations of its name.
    `gh run view --log-failed` refuses until the whole run finishes; the jobs endpoint does not."""
    tries, stuck_names = state.get("ci_tries", {}), stuck(jobs, state)
    return [{"ref": f"ci:{c['id']}", "kind": "ci", "name": c["name"], "url": c["html_url"], "id": c["id"],
             "run": int(re.search(r"/runs/(\d+)/", c["html_url"])[1]), "refuted_before": tries.get(c["name"], []),
             "log": LOG_NOISE.sub("", sh(["gh", "api", "--allow-escape-sequences",
                                         f"repos/{REPO}/actions/jobs/{c['id']}/logs"]))[-CI_LOG_CHARS:]}
            for c in jobs if failed(c) and c["id"] not in state.get("handled_jobs", []) and c["name"] not in stuck_names]


# ---------------------------------------------------------------- worktree

def worktree(meta, red):
    """The PR branch's worktree, created when missing, fast-forwarded to the PR head. Local changes are
    allowed only when they are the work of a tests-red pass, and dropped once the PR head moves on.
    Any other change is stashed: a pass that died mid-way must not park the PR for good."""
    branch, head = meta["headRefName"], meta["headRefOid"]
    for block in sh(["git", "worktree", "list", "--porcelain"]).strip().split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if fields.get("branch") == f"refs/heads/{branch}":
            wt = fields["worktree"]
            break
    else:
        wt = os.path.join(names.worktrees(REPO_ROOT), branch.replace("/", "+"))
        sh(["git", "fetch", "origin", branch])
        local = subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], cwd=REPO_ROOT,
                               capture_output=True).returncode == 0
        sh(["git", "worktree", "add", wt, branch] if local else
           ["git", "worktree", "add", "-b", branch, wt, f"origin/{branch}"])
    stray = dirty(wt) - set(red.get("paths", []))
    if stray:
        sh(["git", "stash", "push", "-q", "-u", "-m", f"pr_fix: stray changes at {head[:12]}", "--", *stray], cwd=wt)
    left = dirty(wt)
    sh(["git", "fetch", "origin", head], cwd=wt)
    if left and red["head"] != head:
        sh(["git", "reset", "-q", "--hard", head], cwd=wt)
        sh(["git", "clean", "-fdq", "--", *left], cwd=wt)
    ancestor = lambda a, b: subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=wt).returncode == 0
    if ancestor("HEAD", head):
        sh(["git", "merge", "--ff-only", "-q", head], cwd=wt)
    elif not ancestor(head, "HEAD"):
        die(f"{wt} holds commits that PR head {head[:12]} does not")
    return wt


def merge_prompt(pr, meta, files, conv):
    return (conventions.fill(open(MERGE_PROMPT).read(), conv)
            .replace("{FILES}", "\n".join(f"- `{f}`" for f in files))
            .replace("{BRIEF}", brief({"pr": pr, "branch": meta["headRefName"]}))
            .replace("{PR}", str(pr)).replace("{REPO}", REPO).replace("{BASE}", f"origin/{meta['baseRefName']}")
            .replace("{SCHEMA}", open(SCHEMA).read()))


def fix_prompt(pr, meta, feedback_path, conv):
    return (gates.fill(conventions.fill(open(PROMPT).read(), conv), GATES)
            .replace("{BRIEF}", brief({"pr": pr, "branch": meta["headRefName"]}))
            .replace("{FEEDBACK}", feedback_path).replace("{PR}", str(pr)).replace("{REPO}", REPO)
            .replace("{HEAD}", meta["headRefOid"]).replace("{BASE}", f"origin/{meta['baseRefName']}")
            .replace("{SCHEMA}", open(SCHEMA).read()))


def project_conventions(wt, meta, items):
    """The conventions for the paths the feedback names and the paths the branch changes."""
    sh(["git", "fetch", "-q", "origin", meta["baseRefName"]], cwd=wt)
    diff = sh(["git", "diff", "--name-only", f"origin/{meta['baseRefName']}...HEAD"], cwd=wt).splitlines()
    return conventions.collect(wt, [*(i["path"] for i in items if i.get("path")), *diff])


def merge(pr, wt, meta, session, scratch, conv):
    """Merges the base into the branch and commits it; Codex resolves any conflict.
    (session, False) when Codex is at its usage limit."""
    base = f"origin/{meta['baseRefName']}"
    sh(["git", "fetch", "-q", "origin", meta["baseRefName"]], cwd=wt)
    out = subprocess.run(["git", "merge", "--no-edit", "-q", base], cwd=wt, capture_output=True, text=True)
    if not out.returncode:
        return session, True
    files = sh(["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt).split()
    try:
        if not files:
            die(f"git merge {base} failed\n{out.stderr.strip()[-2000:]}")
        prompt = merge_prompt(pr, meta, files, conv)
        session, result = codex(wt, prompt, session, scratch)
        if result is None:
            return session, False
        if sh(["git", "grep", "-lE", "^(<<<<<<<|>>>>>>>)( |$)", "--", *files], cwd=wt, check=False).strip():
            die(f"codex left conflict markers in {wt}")
        sh(["git", "add", "-A"], cwd=wt)
        sh(["git", "commit", "--no-edit", "-q"], cwd=wt)
        return session, True
    finally:
        if sh(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=wt, check=False).strip():
            sh(["git", "merge", "--abort"], cwd=wt)


def dirty(wt):
    return {line[3:].split(" -> ")[-1] for line in sh(["git", "status", "--porcelain", "-uall"], cwd=wt).splitlines()}


def changed(wt):
    paths = []
    for line in sh(["git", "status", "--porcelain", "-uall"], cwd=wt).splitlines():
        path = line[3:].split(" -> ")[-1]
        if os.path.exists(os.path.join(wt, path)):
            paths.append(path)
    return paths


# ---------------------------------------------------------------- codex

def codex(wt, prompt, session, scratch):
    """(session id, result JSON) from a sandboxed Codex turn, or (session, None) at its usage limit."""
    common = os.path.abspath(os.path.join(wt, sh(["git", "rev-parse", "--git-common-dir"], cwd=wt).strip()))
    last = os.path.join(scratch, "last.json")
    config = ["-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"',
              "-c", f"sandbox_workspace_write.writable_roots={json.dumps([wt, common, scratch])}",
              *codex_flags(FIX["model"], FIX["effort"])]
    io = ["--json", "--output-schema", SCHEMA, "-o", last]
    args = (["codex", "exec", "resume", *config, *io, session, prompt] if session
            else ["codex", "exec", "-C", wt, *config, *io, prompt])
    out = subprocess.run(args, cwd=wt, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
    if out.returncode:
        if LIMIT.search(f"{out.stdout}\n{out.stderr}"):
            return session, None
        die(f"codex exec exited {out.returncode}\n{out.stderr.strip()[-2000:]}")
    for line in out.stdout.splitlines():
        if '"thread.started"' in line:
            session = json.loads(line)["thread_id"]
    return session, json.load(open(last))


# ---------------------------------------------------------------- gate

def saved(scratch, test):
    path = os.path.join(scratch, re.sub(r"\W+", "-", test["ns"]) + ".log")
    open(path, "w").write(test["log"])
    return path


# ---------------------------------------------------------------- land

def land(wt, branch, head, message, summary):
    """Commits the fix and pushes it, with any commit an earlier pass made but failed to push.
    None when the PR head stays as it was."""
    if changed(wt):
        message = ATTRIBUTION.sub("", message).strip() or f"fix: address review feedback\n\n{summary}"
        with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False) as fh:
            fh.write(message + "\n")
        try:
            sh(["git", "add", "-A"], cwd=wt)
            sh(["git", "commit", "-q", "-F", fh.name], cwd=wt)
        finally:
            os.unlink(fh.name)
    sha = sh(["git", "rev-parse", "HEAD"], cwd=wt).strip()
    if sha == head:
        return None
    sh(["git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}"], cwd=wt)
    return sha


def respond(pr, items, answers, ci_notes):
    """👍 + resolve every fixed thread, reply + resolve every refuted one, one PR comment for refuted review bodies
    and CI jobs, each job with what happens to it next."""
    by_ref = {i["ref"]: i for i in items}
    refuted_bodies = []
    for a in answers:
        item = by_ref.get(a["ref"])
        if not item or a["disposition"] == "deferred":
            continue
        if item["kind"] == "thread" and a["disposition"] == "fixed":
            gh("-X", "POST", f"repos/{REPO}/pulls/comments/{item['top']}/reactions", "-f", "content=+1")
            gh("graphql", "-f", f"query={RESOLVE}", "-f", f"id={item['ref']}")
        elif item["kind"] == "thread" and a["reply"].strip():
            gh("-X", "POST", f"repos/{REPO}/pulls/{pr}/comments/{item['top']}/replies", "-f", f"body={a['reply']}")
            gh("graphql", "-f", f"query={RESOLVE}", "-f", f"id={item['ref']}")
        elif item["kind"] == "review" and a["disposition"] == "refuted" and a["reply"].strip():
            refuted_bodies.append(f"- [{item['author']}'s review]({item['url']}): {a['reply']}")
        elif item["kind"] == "ci" and a["disposition"] == "refuted":
            refuted_bodies.append(f"- [{item['name']}]({item['url']}): {a['reply']} {ci_notes[item['ref']]}")
    if refuted_bodies:
        gh("-X", "POST", f"repos/{REPO}/issues/{pr}/comments", "-f", "body=" + "\n".join(refuted_bodies))


def rerun(jobs):
    """Reruns each job whose run has finished and returns the rest, since GitHub refuses a rerun mid-run."""
    waiting = []
    for job in jobs:
        if gh(f"repos/{REPO}/actions/runs/{job['run']}")["status"] == "completed":
            gh("-X", "POST", f"repos/{REPO}/actions/jobs/{job['id']}/rerun")
        else:
            waiting.append(job)
    return waiting


def run(pr):
    meta = json.loads(sh(["gh", "pr", "view", str(pr), "--repo", REPO, "--json",
                          "state,headRefName,headRefOid,baseRefName,mergeable"]))
    if meta["state"] != "OPEN":
        return {"pr": pr, "status": meta["state"].lower()}
    state = load(pr)
    state.pop("handled_checks", None)
    if state.get("reruns"):
        state["reruns"] = rerun([j for j in state["reruns"] if j["head"] == meta["headRefOid"]])
    jobs = checks(meta["headRefOid"])
    green = {c["name"] for c in jobs if c["conclusion"] == "success"}
    state["ci_tries"] = {n: r for n, r in state.get("ci_tries", {}).items() if n not in green}
    save(pr, state)
    items = feedback(pr, meta["headRefOid"], state) + failed_jobs(jobs, state)
    prior = state.get("red", {})
    resume = prior.get("head") == meta["headRefOid"]
    conflict = meta["mergeable"] == "CONFLICTING" and not resume
    if not items and not conflict and not resume:
        red_jobs = stuck(jobs, state)
        return {"pr": pr, "status": "ci-stuck", "summary": f"{', '.join(red_jobs)} red after {CI_TRIES} refuted looks, "
                                                           f"needs a human"} if red_jobs else \
            {"pr": pr, "status": "nothing-to-fix"}
    wt = worktree(meta, prior)
    conv = project_conventions(wt, meta, items)
    os.makedirs(names.SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix=f"{pr}-", dir=names.SCRATCH)
    try:
        if conflict:
            session, merged = merge(pr, wt, meta, state.get("session"), scratch, conv)
            if not merged:
                return {"pr": pr, "status": "limited", "worktree": wt, "session": session}
            state["session"] = session
            save(pr, state)
        if not items and not resume:
            pushed = land(wt, meta["headRefName"], meta["headRefOid"], "", "")
            return {"pr": pr, "worktree": wt, "status": "pushed" if pushed else "no-changes", "pushed": pushed,
                    "merged": True, "fixed": 0, "refuted": 0, "deferred": 0,
                    "summary": f"merged origin/{meta['baseRefName']}" if pushed else "base already merged"}
        path = os.path.join(scratch, "feedback.json")
        json.dump([{k: v for k, v in i.items() if k not in ("top", "id", "count", "run")} for i in items], open(path, "w"), indent=2)
        prompt = fix_prompt(pr, meta, path, conv)
        session, result = (state.get("session"), prior["result"]) if resume else \
            codex(wt, prompt, state.get("session"), scratch)
        for attempt in range(TEST_RETRIES + 1):
            if result is None:
                return {"pr": pr, "status": "limited", "worktree": wt, "session": session}
            state["session"] = session
            save(pr, state)
            tests = gates.run(GATES, wt, changed(wt))
            red = [t for t in tests if t["ok"] is False]
            if not red or attempt == TEST_RETRIES:
                break
            logs = "\n\n".join(f"### {t['ns']}\nFull log: {saved(scratch, t)}\n...\n{t['log'][-3000:]}" for t in red)
            session, result = codex(wt, gates.retry(GATES, red, logs), session, scratch)
        by_ref = {i["ref"]: i for i in items}
        refuted = [(by_ref[a["ref"]], a["reply"]) for a in result["items"] if a["disposition"] == "refuted"
                   and by_ref.get(a["ref"], {}).get("kind") == "ci"]
        tries = dict(state.get("ci_tries", {}))
        for job, reply in refuted:
            tries[job["name"]] = tries.get(job["name"], []) + [reply]
        retry = [job for job, _ in refuted if len(tries[job["name"]]) < CI_TRIES]
        caught_up = False
        if retry and not red and not changed(wt) and not conflict:
            before = sh(["git", "rev-parse", "HEAD"], cwd=wt).strip()
            session, ok = merge(pr, wt, meta, session, scratch, conv)
            if not ok:
                return {"pr": pr, "status": "limited", "worktree": wt, "session": session}
            caught_up = sh(["git", "rev-parse", "HEAD"], cwd=wt).strip() != before
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    report = {"pr": pr, "worktree": wt, "session": session, "summary": result["summary"], "merged": conflict or caught_up,
              "tests": [{k: t[k] for k in ("ns", "ok")} for t in tests]}
    if red:
        state["red"] = {"head": meta["headRefOid"], "paths": sorted(dirty(wt)), "result": result}
        save(pr, state)
        return {**report, "status": "tests-red", "gate": ", ".join(dict.fromkeys(t["gate"] for t in red)),
                "failing": [t["ns"] for t in red]}
    state.pop("red", None)
    pushed = land(wt, meta["headRefName"], meta["headRefOid"], result["commit_message"], result["summary"])
    base = f"origin/{meta['baseRefName']}"
    respond(pr, items, result["items"], {
        job["ref"]: f"Red after {CI_TRIES} looks, leaving it to a human." if job not in retry
        else f"Merged {base} for a fresh run." if caught_up else "" if pushed else "Rerunning it."
        for job, _ in refuted})
    state["ci_tries"] = tries
    state["handled_reviews"] = state.get("handled_reviews", []) + [i["id"] for i in items if i["kind"] == "review"]
    state["handled_jobs"] = state.get("handled_jobs", []) + [i["id"] for i in items if i["kind"] == "ci"]
    state["reruns"] = state.get("reruns", []) if pushed else rerun(state.get("reruns", []) + [
        {"id": job["id"], "run": job["run"], "head": meta["headRefOid"]} for job in retry])
    state["deferred"] = state.get("deferred", {}) | {
        a["ref"]: by_ref[a["ref"]]["count"] for a in result["items"]
        if a["disposition"] == "deferred" and by_ref.get(a["ref"], {}).get("kind") == "thread"}
    save(pr, state)
    counts = {d: sum(a["disposition"] == d for a in result["items"]) for d in ("fixed", "refuted", "deferred")}
    answered = {a["ref"] for a in result["items"]}
    status = "pushed" if pushed else "refuted-only" if counts["refuted"] else "no-changes"
    return {**report, "status": status, "pushed": pushed, **counts,
            "unanswered": [i["ref"] for i in items if i["ref"] not in answered]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "dump"))
    ap.add_argument("--pr", type=int, required=True)
    a = ap.parse_args()
    names.migrate()
    configure(config.effective_for(REPO, a.pr, cfg=LOADED.config))
    if a.cmd == "dump":
        meta = json.loads(sh(["gh", "pr", "view", str(a.pr), "--repo", REPO, "--json", "headRefOid"]))
        state = load(a.pr)
        return print(json.dumps(feedback(a.pr, meta["headRefOid"], state) + failed_jobs(checks(meta["headRefOid"]), state),
                                indent=2))
    os.makedirs(os.path.dirname(names.lock(REPO, a.pr)), exist_ok=True)
    with open(names.lock(REPO, a.pr, ".fix"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die(f"another fix pass runs on #{a.pr}")
        print(json.dumps(run(a.pr), indent=2))


if __name__ == "__main__":
    main()
