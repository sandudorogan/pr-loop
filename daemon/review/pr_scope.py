#!/usr/bin/env python3
"""What one PR changes, told blind to what it claims, then judged against that claim (the PR Lens passes).

Usage: pr_scope.py run --pr N [--head SHA]

  pass 1  summarize (blind)   cwd: diff.patch, files.json, base/   → intent, changes, touches
  pass 2  judge               cwd: blind.json, claim.json          → stated, verdict, reason, scope[]
          merge               → one JSON object on stdout

Pass 1 never sees the title, the body, the branch name or a commit message: it runs in a fresh temp dir without
.git that holds the diff, the file list and the base branch's copy of the changed directories. Files under
docs/plans/ stay out of it, and the merge lists them as one chore. Exit 1 with the cause on stderr; exit 2 when Codex
is at its usage limit, so the lane retries without counting an error.
"""
import argparse, json, os, re, subprocess, sys, tempfile

DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(DIR))
from pr_loop import config, names

PASSES = os.path.join(DIR, "scope")
REPO = names.env_repo()
ROOT = names.env_root(REPO)
PLANS = "docs/plans/"
LIMIT = re.compile(r"(usage|spend|session|rate) limit|hit your \S+ limit|quota exceeded", re.I)


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=True).stdout


def pull(n):
    return json.loads(subprocess.run(["gh", "api", f"repos/{REPO}/pulls/{n}"], capture_output=True, text=True,
                                     check=True).stdout)


def plan(path):
    return path.startswith(PLANS)


def numstat(text):
    count = lambda v: 0 if v == "-" else int(v)
    return [{"path": p, "additions": count(a), "deletions": count(d)}
            for a, d, p in (line.split("\t", 2) for line in text.splitlines())]


def without_plans(diff):
    return "".join(s for s in re.split(r"^(?=diff --git )", diff, flags=re.M)
                   if not s.startswith(f"diff --git a/{PLANS}"))


def snapshot(base, files, into):
    """The base branch's copy of the changed files' directories, without .git. Root files stay out."""
    dirs = sorted({os.path.dirname(f["path"]) for f in files} - {""})
    listed = [d for d in git("ls-tree", "-d", "--name-only", "-z", base, "--", *dirs).split("\0") if d] if dirs else []
    if listed:
        os.makedirs(target := os.path.join(into, "base"))
        tar = subprocess.run(["git", "-C", ROOT, "archive", "--format=tar", base, "--", *listed],
                             capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", target], input=tar, check=True)


def write(into, name, value):
    with open(os.path.join(into, name), "w") as fh:
        fh.write(value if isinstance(value, str) else json.dumps(value, indent=2))


def codex(name, cwd, knobs):
    with open(os.path.join(PASSES, f"{name}.md")) as fh:
        prompt = fh.read()
    flags = [*(["-c", f"model={json.dumps(knobs['model'])}"] if knobs["model"] else []),
             *(["-c", f"model_reasoning_effort={json.dumps(knobs['effort'])}"] if knobs["effort"] else [])]
    with tempfile.NamedTemporaryFile("r", suffix=".json") as last:
        try:
            out = subprocess.run(["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-C", cwd,
                                  "--output-schema", os.path.join(PASSES, f"{name}-schema.json"),
                                  "--output-last-message", last.name, *flags, prompt],
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=knobs["timeout_s"])
        except subprocess.TimeoutExpired:
            die(f"codex {name} timed out after {knobs['timeout_s']} s")
        if out.returncode:
            LIMIT.search(f"{out.stdout}\n{out.stderr}") and die("codex is at its usage limit", 2)
            die(f"codex {name} exited {out.returncode}: {out.stderr.strip()[-500:]}")
        return json.loads(last.read())


def merge(blind, judge, dropped):
    scope = {s["index"]: s for s in judge["scope"]}
    if missing := [i for i in range(len(blind["changes"])) if i not in scope]:
        die(f"the judge skipped change {missing[0]}")
    changes = [dict(c, in_scope=scope[i]["in_scope"], note=scope[i]["note"]) for i, c in enumerate(blind["changes"])]
    if dropped:
        changes.append({"kind": "chore", "area": "Docs › Plans", "what": "Adds or updates the PR plan file",
                        "files": dropped, "in_scope": True, "note": ""})
    return {"verdict": judge["verdict"], "reason": judge["reason"], "intent": blind["intent"],
            "stated": judge["stated"], "changes": changes, "touches": blind["touches"]}


def run(n, head):
    knobs, pr = config.load().config["scope"], pull(n)
    head = head or pr["head"]["sha"]
    git("fetch", "-q", "--no-tags", "origin", pr["base"]["ref"], head)
    base = git("merge-base", f"origin/{pr['base']['ref']}", head).strip()
    files = numstat(git("diff", "--numstat", "--no-renames", base, head))
    shown = [f for f in files if not plan(f["path"])]
    with tempfile.TemporaryDirectory(prefix="prl-") as cwd:
        write(cwd, "diff.patch", without_plans(git("diff", "--no-color", "--no-ext-diff", "--no-renames", base, head)))
        write(cwd, "files.json", shown)
        snapshot(base, shown, cwd)
        blind = codex("summarize", cwd, knobs)
    with tempfile.TemporaryDirectory(prefix="prl-") as cwd:
        write(cwd, "blind.json", blind)
        write(cwd, "claim.json", {"title": pr["title"], "body": pr["body"] or "", "headRef": pr["head"]["ref"]})
        judge = codex("judge", cwd, knobs)
    return merge(blind, judge, [f["path"] for f in files if plan(f["path"])])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.pr, args.head)))
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr or ""
        die(f"{' '.join(e.cmd[:4])} failed: {err.strip()[-300:]}")


if __name__ == "__main__":
    main()
