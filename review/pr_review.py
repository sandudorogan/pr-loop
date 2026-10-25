#!/usr/bin/env python3
"""PR review fan-out — run a fresh-context reviewer against a PR and post its
findings as one attributed review with inline comments.

Usage:
  pr_review.py scope --pr N
  pr_review.py run   --pr N --reviewer <opus|codex|quality> [--force]
  pr_review.py post  --pr N --reviewer <opus|codex|quality> --findings <file.json>

A review that found nothing posts nothing — an empty review is noise, and it means
the cycle should stop rather than order another round. `run` says so in its output:

    {"posted": false, "reason": "no-findings", "stop": true}

A review whose findings are all below the fix floor (medium and up at confidence 0.6; high and
up from round 4, so late rounds stop on nits) posts as notes only, marked
`<!-- agent-review-fyi -->`, and also returns `"stop": true`.

Anything the caller must act on is therefore on the PR. Every posted review carries

    <!-- agent-review: reviewer=<id> round=<n> sha=<head> -->

which records who reviewed which head; `scope` reads those markers back to derive the
next round number and the base to diff against, so a fresh session picks up exactly
where the last one stopped. A `briefs/<N>.md` (or `briefs/<branch, / → +>.md`, written before
the PR existed) beside this script is the task the PR was opened for; the opus reviewer also
checks the change against it. The one thing the PR cannot record is a round that found
nothing, so those go in a local `.clean-reviews.json` — purely to avoid re-running a
reviewer over a head it already cleared. Losing that file costs one redundant review.

The same marker is what makes these reviews visible to the PR watch loop: its
scanner skips comments authored by the repo owner, and these are posted under the
owner's token. See `skills/pr-review-loop/scan.py`.
"""
import argparse, fcntl, json, os, re, subprocess, sys, tempfile

DIR = os.path.dirname(os.path.realpath(__file__))
SCHEMA = os.path.join(DIR, "review-schema.json")
PROMPTS = os.path.join(DIR, "prompts")

REPO = os.environ.get("IPR_REPO", "iprally/iprally")
REPO_ROOT = os.environ.get("IPR_REPO_ROOT", os.path.expanduser(f"~/workdir/{REPO.split('/')[1]}"))
TIMEOUT = int(os.environ.get("IPR_REVIEW_TIMEOUT", "2700"))

INLINE_SEVERITIES = {"critical", "high", "medium"}
LATE_SEVERITIES = {"critical", "high"}
LATE_ROUND = 4
MIN_CONFIDENCE = 0.6
FYI_MARKER = "<!-- agent-review-fyi -->"

CLEAN_CACHE = os.path.expanduser("~/.claude/skills/delegator/.clean-reviews.json")

MARKER_PREFIX = "<!-- agent-review:"
MARKER_RE = re.compile(
    r"<!--\s*agent-review:\s*reviewer=(\S+)\s+round=(\d+)\s+sha=(\S+)\s*-->")

REVIEWERS = {
    "opus": {"label": "Claude Opus 5.5", "prompt": "opus.md", "engine": "claude", "claude": ("opus", "high"),
             "fix_round": ("opus", "medium")},
    "codex": {"label": "Codex", "prompt": "codex.md", "engine": "codex", "claude": ("opus", None)},
    "quality": {"label": "Claude Haiku 5.5 · quality self-review", "prompt": "quality.md", "engine": "claude",
                "claude": ("haiku", "xhigh")},
}
BRIEFS = os.path.expanduser("~/.claude/skills/delegator/briefs")
ENGINE_LABELS = {"claude": "Claude", "codex": "Codex"}
LIMIT = re.compile(r"(usage|spend|session|rate) limit|hit your \S+ limit|quota exceeded", re.I)


def clean_cache():
    """Rounds that found nothing post no review, so they leave no marker on the PR; notes-only
    rounds post one but leave nothing to fix. This remembers both only to avoid re-running a reviewer over a head it already cleared. Losing
    the file costs one redundant review and nothing else — everything that matters is still on
    the PR."""
    try:
        return json.load(open(CLEAN_CACHE))
    except (OSError, ValueError):
        return {}


def record_clean(pr, sha, reviewer):
    cache = clean_cache()
    cache.setdefault(f"{pr}/{sha}", [])
    if reviewer not in cache[f"{pr}/{sha}"]:
        cache[f"{pr}/{sha}"].append(reviewer)
    for key in list(cache)[:-40]:
        del cache[key]
    json.dump(cache, open(CLEAN_CACHE, "w"), indent=2)


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sh(args, cwd=None, timeout=120, check=True):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and out.returncode != 0:
        die(f"{' '.join(args[:4])}… exited {out.returncode}\n{out.stderr.strip()}")
    return out


def gh_json(path, paginate=False):
    if not paginate:
        return json.loads(sh(["gh", "api", path]).stdout or "null")
    items, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        chunk = json.loads(sh(["gh", "api", f"{path}{sep}per_page=100&page={page}"]).stdout or "[]")
        items.extend(chunk)
        if len(chunk) < 100:
            return items
        page += 1


# ---------------------------------------------------------------- scope

def pr_meta(pr):
    return json.loads(sh([
        "gh", "pr", "view", str(pr), "--repo", REPO, "--json",
        "number,state,headRefName,headRefOid,baseRefName,title,isDraft"]).stdout)


def markers(pr):
    """Every agent review already on the PR, oldest round first."""
    found = []
    for r in gh_json(f"repos/{REPO}/pulls/{pr}/reviews", paginate=True):
        m = MARKER_RE.search(r.get("body") or "")
        if m:
            found.append({"reviewer": m.group(1), "round": int(m.group(2)),
                          "sha": m.group(3), "submitted_at": r.get("submitted_at") or ""})
    return sorted(found, key=lambda x: (x["round"], x["submitted_at"]))


def linear_since(sha, head):
    """True when sha..head holds only the PR's own commits: sha is still an ancestor, no merges."""
    sh(["git", "fetch", "origin", head], cwd=REPO_ROOT, timeout=600, check=False)
    if sh(["git", "merge-base", "--is-ancestor", sha, head], cwd=REPO_ROOT, check=False).returncode:
        return False
    return not sh(["git", "rev-list", "--merges", f"{sha}..{head}"], cwd=REPO_ROOT).stdout.strip()


def scope(pr):
    meta = pr_meta(pr)
    head = meta["headRefOid"]
    base_branch = meta["baseRefName"]
    prior = markers(pr)

    at_head = [m for m in prior if m["sha"] == head]
    if at_head:
        rnd = at_head[0]["round"]
    else:
        rnd = (max((m["round"] for m in prior), default=0)) + 1

    earlier = [m for m in prior if m["sha"] != head and m["round"] < rnd]
    last_sha = earlier[-1]["sha"] if earlier else None
    base_sha = last_sha if last_sha and linear_since(last_sha, head) else None

    if base_sha:
        diff_range, base_ref = f"{base_sha}..{head}", base_sha
        note = (f"This is review round {rnd}. Round {rnd - 1} already reviewed everything up to "
                f"`{base_sha[:12]}` and its findings are on the PR as comments. Review ONLY the "
                f"commits added since then. Do not re-report round {rnd - 1}'s findings.")
    elif last_sha:
        diff_range, base_ref = f"origin/{base_branch}...{head}", f"origin/{base_branch}"
        note = (f"This is review round {rnd}. The branch was rebased or merged {base_branch} since "
                f"round {rnd - 1}, so review the whole change against {base_branch}. Earlier rounds' "
                f"findings are on the PR as comments. Do not re-report them.")
    else:
        diff_range, base_ref = f"origin/{base_branch}...{head}", f"origin/{base_branch}"
        note = f"This is review round {rnd} — the first review of this PR. Review the whole change."

    posted_at_head = {m["reviewer"] for m in at_head}
    clean_at_head = set(clean_cache().get(f"{pr}/{head}", []))
    seen_at_head = posted_at_head | clean_at_head

    return {
        "pr": int(pr), "state": meta["state"], "draft": meta["isDraft"],
        "title": meta["title"], "branch": meta["headRefName"], "head": head,
        "base_branch": base_branch, "base_ref": base_ref, "base_sha": base_sha,
        "round": rnd,
        "diff_range": diff_range, "round_note": note,
        "done_at_head": sorted(seen_at_head),
        "posted_at_head": sorted(posted_at_head),
        "clean_at_head": sorted(clean_at_head),
        # Every reviewer has looked at this head and none of them left anything to fix.
        # Nothing is going to happen on this PR without a human or a new push — stop the cycle.
        "settled": set(REVIEWERS) <= clean_at_head,
        "history": prior,
    }


# ---------------------------------------------------------------- diff map

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def commentable_lines(pr):
    """Right-hand line numbers GitHub will accept an inline comment on."""
    table = {}
    for f in gh_json(f"repos/{REPO}/pulls/{pr}/files", paginate=True):
        patch, lines = f.get("patch"), set()
        if not patch:
            table[f["filename"]] = lines
            continue
        new_line = 0
        for row in patch.splitlines():
            h = HUNK_RE.match(row)
            if h:
                new_line = int(h.group(1))
                continue
            if row.startswith("-"):
                continue
            if row.startswith("+") or row.startswith(" "):
                lines.add(new_line)
                new_line += 1
        table[f["filename"]] = lines
    return table


# ---------------------------------------------------------------- reviewers

def brief(sc):
    """The task the PR was opened for, written by the delegator to briefs/<N>.md or, before the PR
    existed, to briefs/<branch with / → +>.md."""
    for name in (sc["pr"], sc["branch"].replace("/", "+")):
        path = os.path.join(BRIEFS, f"{name}.md")
        if os.path.exists(path):
            return f"<task>\n{open(path).read().strip()}\n</task>"
    return ""


def render(name, sc):
    text = open(os.path.join(PROMPTS, name)).read()
    return (text
            .replace("{BRIEF}", brief(sc))
            .replace("{PR}", str(sc["pr"]))
            .replace("{REPO}", REPO)
            .replace("{HEAD}", sc["head"])
            .replace("{BASE}", sc["base_ref"])
            .replace("{DIFF_RANGE}", sc["diff_range"])
            .replace("{ROUND_NOTE}", sc["round_note"])
            .replace("{SCHEMA}", open(SCHEMA).read()))


def extract_json(text):
    fences = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    for block in reversed(fences):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    decoder, start = json.JSONDecoder(), text.find("{")
    while start != -1:
        try:
            return decoder.raw_decode(text, start)[0]
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    die("reviewer returned no parsable JSON object")


def child_env():
    """A harness-scoped ANTHROPIC_API_KEY is not valid for a standalone `claude`, and it
    outranks the user's claude.ai login. Drop it so the child authenticates the way an
    interactive session does."""
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    return env


def claude_p(worktree, prompt, model, effort=None):
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", model,
         "--disallowedTools", "Edit,Write,NotebookEdit",
         "--output-format", "text", *(["--effort", effort] if effort else [])],
        cwd=worktree, env=child_env(), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=TIMEOUT)
    if out.returncode != 0:
        at_limit(out)
        # The 401 from an inherited ANTHROPIC_API_KEY lands on stdout, not stderr.
        die(f"claude -p exited {out.returncode}\n"
            f"--- stderr ---\n{out.stderr.strip()[:2000]}\n"
            f"--- stdout ---\n{out.stdout.strip()[:2000]}")
    return out.stdout


def codex_exec(worktree, prompt):
    with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as fh:
        last = fh.name
    try:
        out = subprocess.run(
            ["codex", "exec", "-C", worktree, "-s", "read-only",
             "--output-schema", SCHEMA, "--output-last-message", last, prompt],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
        if out.returncode != 0:
            at_limit(out)
            die(f"codex exec exited {out.returncode}\n{out.stderr.strip()[:2000]}")
        return open(last).read().strip() or die("codex wrote no final message")
    finally:
        os.unlink(last)


class AtLimit(Exception):
    pass


def at_limit(out):
    text = f"{out.stdout}\n{out.stderr}"
    if match := LIMIT.search(text):
        raise AtLimit(text[max(0, match.start() - 80):match.end() + 120].strip())


ENGINES = {
    "claude": lambda worktree, prompt, model, effort: claude_p(worktree, prompt, model, effort),
    "codex": lambda worktree, prompt, *_: codex_exec(worktree, prompt),
}
OTHER = {"claude": "codex", "codex": "claude"}


def run_reviewer(reviewer, worktree, sc):
    """(engine, findings) from the reviewer's own engine, or from the other one when its own
    is at its usage limit. A plain prompt, not `/review`: in `-p` the native command returns
    "(none)" without reviewing."""
    spec = REVIEWERS[reviewer]
    prompt = render(spec["prompt"], sc)
    claude = spec.get("fix_round", spec["claude"]) if sc["base_sha"] else spec["claude"]
    for engine in (spec["engine"], OTHER[spec["engine"]]):
        try:
            return engine, extract_json(ENGINES[engine](worktree, prompt, *claude))
        except AtLimit as e:
            print(f"{engine} at its usage limit: {e}", file=sys.stderr)
    die("claude and codex are both at their usage limit")


# ---------------------------------------------------------------- worktree

def review_worktree(pr, head):
    """The PR's one detached checkout, shared by its reviewers and moved to each new head.

    `review-queue --prune` removes it once the PR is merged or approved.
    """
    root = os.path.join(REPO_ROOT, ".claude", "worktrees")
    path = os.path.join(root, f".review-{pr}")
    sh(["git", "fetch", "origin", head], cwd=REPO_ROOT, timeout=600, check=False)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, ".review.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(path):
            sh(["git", "worktree", "add", "--detach", path, head], cwd=REPO_ROOT, timeout=600)
        elif sh(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip() != head:
            sh(["git", "checkout", "--force", "--detach", head], cwd=path, timeout=600)
            sh(["git", "clean", "-fdq"], cwd=path)
    return path


# ---------------------------------------------------------------- posting

def marker(reviewer, rnd, sha):
    return f"{MARKER_PREFIX} reviewer={reviewer} round={rnd} sha={sha} -->"


def finding_line(f):
    return f"**[{f['severity']}]** `{f['file']}:{f['line_start']}` — {f['title']}\n\n{f['body']}\n\n_Fix:_ {f.get('recommendation') or '—'}"


def inline_body(f, label, mk):
    rec = f.get("recommendation")
    parts = [mk, f"**[{f['severity']}] {f['title']}**", "", f["body"]]
    if rec:
        parts += ["", f"**Recommendation:** {rec}"]
    parts += ["", f"<sub>{label} · confidence {f.get('confidence', 0):.2f}</sub>"]
    return "\n".join(parts)


def to_fix(findings, rnd):
    """The findings a fixer must act on. From LATE_ROUND on only high and critical ones count."""
    floor = LATE_SEVERITIES if rnd >= LATE_ROUND else INLINE_SEVERITIES
    return [f for f in findings if f.get("severity") in floor and float(f.get("confidence", 0)) >= MIN_CONFIDENCE]


def split_findings(findings, table):
    inline, carried = [], []
    for f in findings:
        strong = (f.get("severity") in INLINE_SEVERITIES
                  and float(f.get("confidence", 0)) >= MIN_CONFIDENCE)
        ok = table.get(f.get("file"))
        end = f.get("line_end") or f.get("line_start")
        if strong and ok and end in ok:
            inline.append(f)
        else:
            carried.append(f)
    return inline, carried


def build_body(sc, reviewer, label, data, inline, carried, mk, fyi):
    verdict = data.get("verdict", "needs-attention")
    badge = "notes only, nothing to fix" if fyi else "needs attention" if verdict == "needs-attention" else "approve"
    span = (f"`{sc['base_sha'][:12]}..{sc['head'][:12]}`" if sc["base_sha"]
            else f"`{sc['base_branch']}...{sc['head'][:12]}`")
    head = [
        f"## Code review — {label}",
        "",
        mk,
        "",
        f"**Reviewer:** {label} · **Verdict:** {badge} · **Round {sc['round']}** · "
        f"reviewed {span} · {len(data.get('findings', []))} finding(s), {len(inline)} inline",
        "",
        data.get("summary", "").strip(),
    ]
    if carried:
        head += ["", f"<details><summary>{len(carried)} finding(s) not anchored to the diff</summary>", ""]
        head += [f"- {finding_line(f)}\n" for f in carried]
        head += ["</details>"]
    steps = data.get("next_steps") or []
    if steps:
        head += ["", "**Next steps**", ""] + [f"- {s}" for s in steps]
    return "\n".join(head)


def post(pr, reviewer, data, sc, dry_run=False, engine=None):
    label = REVIEWERS[reviewer]["label"]
    if engine and engine != REVIEWERS[reviewer]["engine"]:
        label += f" · run on {ENGINE_LABELS[engine]}"
    findings = data.get("findings") or []
    fyi = not to_fix(findings, sc["round"])
    mk = marker(reviewer, sc["round"], sc["head"]) + (f"\n{FYI_MARKER}" if fyi else "")
    table = commentable_lines(pr)
    inline, carried = split_findings(findings, table)

    comments = []
    for f in inline:
        ok = table[f["file"]]
        c = {"path": f["file"], "line": f.get("line_end") or f["line_start"],
             "side": "RIGHT", "body": inline_body(f, label, mk)}
        start = f.get("line_start")
        if start and start < c["line"] and start in ok:
            c["start_line"], c["start_side"] = start, "RIGHT"
        comments.append(c)

    if not findings:
        if not dry_run:
            record_clean(pr, sc["head"], reviewer)
        return {"posted": False, "stop": True, "reason": "no-findings", "round": sc["round"],
                "verdict": data.get("verdict"), "findings": 0, "inline": 0,
                "summary": (data.get("summary") or "").strip()}

    payload = {"commit_id": sc["head"], "event": "COMMENT",
               "body": build_body(sc, reviewer, label, data, inline, carried, mk, fyi),
               "comments": comments}
    if dry_run:
        return {"dry_run": True, "posted": False, "would_post": True, "stop": fyi,
                "payload": payload, "inline": len(inline),
                "summary_only": len(carried), "findings": len(findings)}

    res = submit(pr, payload)
    if res is None and comments:
        # A single out-of-diff anchor 422s the whole review. Fall back to
        # summary-only so the findings still reach the PR.
        print("inline anchors rejected — retrying with every finding in the summary",
              file=sys.stderr)
        payload["body"] = build_body(sc, reviewer, label, data, [], findings, mk, fyi)
        payload["comments"] = []
        res = submit(pr, payload)
        inline = []
    if res is None:
        die("could not post the review")
    if fyi:
        record_clean(pr, sc["head"], reviewer)
    return {"posted": True, "stop": fyi, **({"reason": "notes-only"} if fyi else {}),
            "review_id": res.get("id"), "url": res.get("html_url"),
            "inline": len(inline), "summary_only": len(findings) - len(inline),
            "findings": len(findings), "verdict": data.get("verdict")}


def submit(pr, payload):
    out = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{REPO}/pulls/{pr}/reviews", "--input", "-"],
        input=json.dumps(payload), capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        print(out.stderr.strip()[:1200], file=sys.stderr)
        return None
    return json.loads(out.stdout or "{}")


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scope"); s.add_argument("--pr", required=True)

    r = sub.add_parser("run")
    r.add_argument("--pr", required=True)
    r.add_argument("--reviewer", required=True, choices=sorted(REVIEWERS))
    r.add_argument("--force", action="store_true", help="re-review a head already reviewed")
    r.add_argument("--dry-run", action="store_true", help="print the review payload, post nothing")

    p = sub.add_parser("post")
    p.add_argument("--pr", required=True)
    p.add_argument("--reviewer", required=True, choices=sorted(REVIEWERS))
    p.add_argument("--findings", required=True)
    p.add_argument("--dry-run", action="store_true", help="print the review payload, post nothing")

    a = ap.parse_args()
    sc = scope(a.pr)

    if a.cmd == "scope":
        print(json.dumps(sc, indent=2)); return

    if a.cmd == "post":
        print(json.dumps(post(a.pr, a.reviewer, json.load(open(a.findings)), sc, a.dry_run), indent=2)); return

    if a.reviewer in sc["done_at_head"] and not a.force:
        clean = a.reviewer in sc["clean_at_head"]
        print(json.dumps({"reviewer": a.reviewer, "posted": False,
                          "skipped": "already-reviewed", "stop": clean,
                          "message": f"{a.reviewer} already reviewed {sc['head'][:12]}"
                                     + (" and found nothing" if clean else "")}, indent=2))
        return

    engine, data = run_reviewer(a.reviewer, review_worktree(a.pr, sc["head"]), sc)
    # `stop` is set by post() on every path: true only when there is genuinely nothing for a
    # fixer to act on. A dry run that would have posted is NOT a stop.
    result = post(a.pr, a.reviewer, data, sc, a.dry_run, engine)
    print(json.dumps({"reviewer": a.reviewer, "engine": engine, "round": sc["round"], **result}, indent=2))


if __name__ == "__main__":
    main()
