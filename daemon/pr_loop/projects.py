"""Detected projects (api.md §4.7): the four searches of the queue fetch, the checkout scan of `detect.roots`, and
each project's status.

  search mine · requested · assigned · reviewed ──▶ repos ∪ config.projects ──▶ project ◀── checkout scan
  (one GraphQL call, no repo: filter)                                            status   (detect.roots/*/ remotes)
"""
import os, re, subprocess, threading, time
from glob import glob

from pr_loop import config, conventions

SEARCHES = {"mine": "author:@me", "requested": "user-review-requested:@me", "assigned": "assignee:@me",
            "reviewed": "reviewed-by:@me -author:@me"}
PAGE = 50
RESULT = "issueCount pageInfo { hasNextPage endCursor } nodes { ...pr }"
REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")
RESCAN, RETRY = 1800, 60


def query(fragment):
    args = ", ".join(f"${alias}: String!" for alias in SEARCHES)
    fields = "".join(f"\n  {alias}: search(query: ${alias}, type: ISSUE, first: {PAGE}) {{ {RESULT} }}" for alias in SEARCHES)
    return f"query({args}) {{\n  rateLimit {{ cost remaining }}{fields}\n}}" + fragment


def page_query(fragment):
    return ("query($q: String!, $after: String!) {\n  rateLimit { cost remaining }\n"
            f"  page: search(query: $q, type: ISSUE, first: {PAGE}, after: $after) {{ {RESULT} }}\n}}" + fragment)


def fetch(graphql, fragment, note):
    """({alias: [PR node]}, points spent, points left) of the four searches. A search with more than one page
    fetches the rest on its own, so no PR drops off."""
    terms = {alias: f"is:pr is:open {term}" for alias, term in SEARCHES.items()}
    data = graphql(query(fragment), terms)
    found, cost, left = {}, data["rateLimit"]["cost"], data["rateLimit"]["remaining"]
    for alias, terms_of in terms.items():
        result, nodes = data[alias], list(data[alias]["nodes"])
        while result["pageInfo"]["hasNextPage"]:
            note(f"search page {len(nodes) // PAGE + 1} for {alias} ({result['issueCount']} PRs)")
            page = graphql(page_query(fragment), {"q": terms_of, "after": result["pageInfo"]["endCursor"]})
            result, cost, left = page["page"], cost + page["rateLimit"]["cost"], page["rateLimit"]["remaining"]
            nodes += result["nodes"]
        found[alias] = nodes
    return found, cost, left


def remotes(path):
    """The `owner/name` of every GitHub remote of the checkout at `path`."""
    out = subprocess.run(["git", "-C", path, "config", "--get-regexp", r"^remote\..*\.url$"],
                         capture_output=True, text=True).stdout
    return {m[1] for line in out.splitlines() if (m := REMOTE.search(line.split(" ", 1)[-1]))}


def scan(roots):
    """{repo: dir} of the main checkouts right under `roots`. A dir named like the repo wins, else the first."""
    found = {}
    for d in sorted(d.rstrip("/") for root in roots for d in glob(os.path.join(os.path.expanduser(root), "*", ""))):
        if os.path.isdir(os.path.join(d, ".git")):
            for repo in remotes(d):
                found.setdefault(repo, []).append(d)
    return {repo: next((d for d in dirs if os.path.basename(d) == repo.split("/")[1]), dirs[0])
            for repo, dirs in found.items()}


def resolve(cfg, scanned):
    """{repo: {path, source} | {error}}: the scan, overridden by every `projects[repo].root`."""
    found = {repo: {"path": d, "source": "detected"} for repo, d in scanned.items()}
    for repo, override in cfg["projects"].items():
        if root := (override or {}).get("root"):
            path = os.path.expanduser(root)
            found[repo] = {"path": path, "source": "config"} if repo in remotes(path) \
                else {"error": f"{root} is not a checkout of {repo}"}
    return found


class Checkouts:
    """`resolve()` cached. It scans again after RESCAN, when `detect.roots` or a root changes, and at most once
    every RETRY while a wanted repo has no checkout."""

    def __init__(self, scan=scan):
        self.scan, self.key, self.at, self.found, self.lock = scan, None, 0, {}, threading.Lock()

    def get(self, cfg, wanted=()):
        key = cfg["detect"]["roots"], [(repo, (o or {}).get("root")) for repo, o in cfg["projects"].items()]
        with self.lock:
            age = time.monotonic() - self.at
            if key != self.key or age > RESCAN or age > RETRY and set(wanted) - self.found.keys():
                self.found, self.key, self.at = resolve(cfg, self.scan(cfg["detect"]["roots"])), key, time.monotonic()
            return self.found


def repos(cfg, prs):
    """The config's projects, then every other repo of the fetch in name order."""
    keys = list(cfg["projects"])
    return keys + sorted({pr["repo"] for pr in prs} - set(keys))


class Conventions:
    """`conventions.names()` of each checkout's default branch, cached per (repo, ref sha). One `for-each-ref` call
    reads the ref and its sha, and `ls-tree` runs again only when the sha moves."""

    def __init__(self, names=conventions.names):
        self.names, self.cache, self.lock = names, {}, threading.Lock()

    def get(self, repo, path):
        """`{ref, files, skills}` at `origin/<default branch>`, or None when the checkout has no origin/HEAD."""
        out = subprocess.run(["git", "-C", path, "for-each-ref", "--format=%(symref:short) %(objectname)",
                              "refs/remotes/origin/HEAD"], capture_output=True, text=True).stdout.split()
        if len(out) != 2:
            return None
        ref, sha = out
        with self.lock:
            if (repo, sha) not in self.cache:
                self.cache = {k: v for k, v in self.cache.items() if k[0] != repo}
                self.cache[repo, sha] = self.names(path, ref)
            return self.cache[repo, sha]


CONVENTIONS = Conventions()


def gates(repo, on):
    """The effective fixer gates as `{name, kind, source}`: `default` while they match the built-in config."""
    built = config.effective(config.DEFAULTS, repo)["fix"]["gates"]
    return [{"name": g["name"], "kind": g["kind"], "source": "default" if on["fix"]["gates"] == built else "config"}
            for g in on["fix"]["gates"]]


def project(repo, cfg, found, prs, names=None):
    on, where = config.effective(cfg, repo), found.get(repo, {})
    checkout = where if "path" in where else None
    review, fix = bool(checkout) and on["review"]["enabled"], bool(checkout) and on["fix"]["enabled"]
    status = "error" if "error" in where else "no-checkout" if not checkout else "active" if review or fix else "off"
    return {"repo": repo, "status": status, "available": bool(checkout), "review": review, "fix": fix,
            "checkout": checkout, "prs": prs, "error": where.get("error"), "gates": gates(repo, on),
            "conventions": names(repo, checkout["path"]) if names and checkout else None}


def listing(prs, cfg, found, names=None):
    """The §3.2 `projects[]`: every repo of the fetch or the config, with its checkout, status, gates and, when
    `names(repo, path)` is given, the conventions of each checkout."""
    return [project(repo, cfg, found, sum(pr["repo"] == repo for pr in prs), names) for repo in repos(cfg, prs)]
