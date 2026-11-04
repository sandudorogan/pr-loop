import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from prs import GITOPS, MONOREPO, pr, rq
from pr_loop import config, conventions, projects

SITE, MINE = "clojure/clojurescript-site", "sandudorogan/dataspex"


def result(nodes, more=None, count=None):
    return {"issueCount": count or len(nodes), "pageInfo": {"hasNextPage": more is not None, "endCursor": more},
            "nodes": nodes}


class Graphql:
    """Answers the queue query with `first` and each page query with the next of `pages[alias]`."""

    def __init__(self, first, pages=()):
        self.first, self.pages, self.calls = first, {k: list(v) for k, v in dict(pages).items()}, []

    def __call__(self, query, variables):
        self.calls.append(variables)
        if "q" not in variables:
            return {"rateLimit": {"cost": 10, "remaining": 4990}, **{a: self.first.get(a, result([])) for a in projects.SEARCHES}}
        alias = next(a for a, t in projects.SEARCHES.items() if variables["q"].endswith(t))
        return {"rateLimit": {"cost": 1, "remaining": 4989}, "page": self.pages[alias].pop(0)}


class Fetch(unittest.TestCase):
    def test_one_call_has_four_searches_without_a_repo_qualifier(self):
        query = projects.query(rq.FRAGMENT)
        self.assertEqual(query.count("search("), 4)
        self.assertIn("rateLimit { cost remaining }", query)
        gql = Graphql({})
        self.assertEqual(projects.fetch(gql, rq.FRAGMENT, print), (dict.fromkeys(projects.SEARCHES, []), 10, 4990))
        self.assertEqual(gql.calls, [{"mine": "is:pr is:open author:@me",
                                      "requested": "is:pr is:open user-review-requested:@me",
                                      "assigned": "is:pr is:open assignee:@me",
                                      "reviewed": "is:pr is:open reviewed-by:@me -author:@me"}])

    def test_a_search_over_one_page_fetches_its_own_next_pages(self):
        notes = []
        gql = Graphql({"mine": result([1] * 50, "c1", 120), "reviewed": result([9])},
                      {"mine": [result([2] * 50, "c2", 120), result([3] * 20, None, 120)]})
        found, cost, left = projects.fetch(gql, rq.FRAGMENT, notes.append)
        self.assertEqual((len(found["mine"]), found["reviewed"], cost, left), (120, [9], 12, 4989))
        self.assertEqual([c.get("after") for c in gql.calls], [None, "c1", "c2"])
        self.assertEqual(notes, ["search page 2 for mine (120 PRs)", "search page 3 for mine (120 PRs)"])

    def fetched(self, **found):
        gql = Graphql({alias: result(nodes) for alias, nodes in found.items()})
        with patch.object(rq, "graphql", return_value=gql):
            return rq.fetched()

    def test_assigned_prs_join_the_queue_and_count_as_review_requests(self):
        node = lambda repo, n, **kw: {k: v for k, v in pr(n, repo, mine=False, **kw).items() if k not in ("repo", "requested")}
        prs, cost, _ = self.fetched(assigned=[node(SITE, 4)], requested=[node(MONOREPO, 5)], reviewed=[node(MONOREPO, 5)])
        self.assertEqual([(p["repo"], p["number"], p["requested"]) for p in prs], [(SITE, 4, True), (MONOREPO, 5, True)])
        self.assertEqual(cost, 10)

    def test_an_assignment_is_no_request_on_my_own_pr_or_after_my_approval(self):
        node = lambda n, mine, approvals=(): {k: v for k, v in pr(n, mine=mine, approvals=approvals).items()
                                              if k not in ("repo", "requested")}
        prs, _, _ = self.fetched(assigned=[node(1, True), node(2, False, [False]), node(3, False, [True])])
        self.assertEqual({p["number"]: p["requested"] for p in prs}, {1: False, 2: True, 3: False})

    def test_an_assigned_colleague_pr_with_no_review_is_queued_at_its_current_head(self):
        node = {k: v for k, v in pr(6, mine=False).items() if k not in ("repo", "requested")}
        (assigned,), _, _ = self.fetched(assigned=[node])
        self.assertIsNone(rq.decide(assigned, {}, {"a.py": "h"}, False))
        self.assertEqual(rq.row(assigned, {}, {}, [])[:2], (1, "queued"))


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class Scan(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = os.path.realpath(temp.name)

    def checkout(self, name, *urls):
        d = os.path.join(self.root, name)
        git("init", "-q", d)
        for i, url in enumerate(urls):
            git("-C", d, "remote", "add", f"r{i}", url)
        return d

    def test_remotes_of_main_checkouts_map_to_their_dirs(self):
        iprally = self.checkout("iprally", "git@github.com:iprally/iprally.git")
        garden = self.checkout("garden", "https://github.com/sandudorogan/garden.git", "ssh://git@github.com/lambdaisland/garden")
        self.checkout("other", "git@gitlab.com:acme/other.git")
        git("-C", iprally, "commit", "-q", "--allow-empty", "-m", "x")
        git("-C", iprally, "worktree", "add", "-q", os.path.join(self.root, "zz-worktree"))
        self.assertEqual(projects.scan([self.root]), {MONOREPO: iprally, "sandudorogan/garden": garden,
                                                      "lambdaisland/garden": garden})

    def test_the_dir_named_like_the_repo_wins_else_the_first(self):
        self.checkout("a-copy", "git@github.com:iprally/gitops.git", "git@github.com:acme/tool.git")
        gitops = self.checkout("gitops", "git@github.com:iprally/gitops")
        self.checkout("b-copy", "git@github.com:acme/tool.git")
        found = projects.scan([self.root])
        self.assertEqual((found[GITOPS], found["acme/tool"]), (gitops, os.path.join(self.root, "a-copy")))

    def test_a_config_root_must_be_a_checkout_of_its_repo(self):
        tools = self.checkout("tools", "git@github.com:acme/tools.git")
        cfg = config.merge(config.DEFAULTS, {"projects": {"acme/tools": {"root": tools}, GITOPS: {"root": tools}}})
        found = projects.resolve(cfg, {GITOPS: "/w/gitops", MONOREPO: "/w/iprally"})
        self.assertEqual(found, {"acme/tools": {"path": tools, "source": "config"}, MONOREPO: {"path": "/w/iprally", "source": "detected"},
                                 GITOPS: {"error": f"{tools} is not a checkout of {GITOPS}"}})


class Status(unittest.TestCase):
    def listing(self, prs, found, overrides=None):
        cfg = config.merge(config.DEFAULTS, {"projects": overrides or {}})
        return {p["repo"]: p for p in projects.listing(prs, cfg, found)}

    def test_every_repo_of_the_fetch_and_the_config_is_a_project_with_its_status(self):
        found = {MONOREPO: {"path": "/w/iprally", "source": "detected"}, GITOPS: {"error": "x is not a checkout"},
                 MINE: {"path": "/w/dataspex", "source": "detected"}, "acme/idle": {"path": "/w/idle", "source": "detected"}}
        got = self.listing([pr(1, MINE), pr(2, SITE), pr(3, SITE), pr(4)], found)
        self.assertEqual(list(got), [MONOREPO, GITOPS, SITE, MINE])
        self.assertEqual({r: (p["status"], p["available"], p["review"], p["fix"], p["prs"], p["error"]) for r, p in got.items()},
                         {MONOREPO: ("active", True, True, True, 1, None), GITOPS: ("error", False, False, False, 0, "x is not a checkout"),
                          SITE: ("no-checkout", False, False, False, 2, None), MINE: ("active", True, True, True, 1, None)})
        self.assertEqual((got[MINE]["checkout"], got[SITE]["checkout"]), ({"path": "/w/dataspex", "source": "detected"}, None))

    def test_a_new_project_inherits_the_defaults_and_both_lanes_off_is_off(self):
        found = {MINE: {"path": "/w/dataspex", "source": "detected"}}
        self.assertEqual(self.listing([pr(1, MINE)], found)[MINE]["status"], "active")
        off = {MINE: {"review": {"enabled": False}, "fix": {"enabled": False}}}
        self.assertEqual(self.listing([pr(1, MINE)], found, off)[MINE]["status"], "off")


class Follows(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = os.path.realpath(temp.name)
        git("init", "-q", self.dir)
        self.cache = projects.Conventions(self.counted)
        self.runs = []

    def counted(self, path, ref):
        self.runs.append(ref)
        return conventions.names(path, ref)

    def land(self, *files):
        for f in files:
            os.makedirs(os.path.dirname(os.path.join(self.dir, f)) or self.dir, exist_ok=True)
            open(os.path.join(self.dir, f), "w").close()
        git("-C", self.dir, "add", "-A")
        git("-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        git("-C", self.dir, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        git("-C", self.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")

    def test_the_names_come_from_the_default_branch_of_the_remote(self):
        self.land("AGENTS.md", "ui/CLAUDE.md", ".claude/skills/lint/SKILL.md")
        self.assertEqual(self.cache.get("a/b", self.dir),
                         {"ref": "origin/trunk", "files": ["AGENTS.md", "ui/CLAUDE.md"], "skills": ["lint"]})

    def test_git_runs_again_only_when_the_ref_moves(self):
        self.land("AGENTS.md")
        for _ in range(3):
            self.cache.get("a/b", self.dir)
        self.assertEqual(len(self.runs), 1)
        self.land("CLAUDE.md")
        self.assertEqual(self.cache.get("a/b", self.dir)["files"], ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(len(self.runs), 2)

    def test_a_checkout_without_origin_head_has_none(self):
        git("-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        self.assertIsNone(self.cache.get("a/b", self.dir))
        self.assertIsNone(self.cache.get("a/b", "/no/such/dir"))
        self.assertEqual(self.runs, [])

    def test_a_listing_reads_only_projects_with_a_checkout(self):
        asked = []
        names = lambda repo, path: asked.append((repo, path)) or {"ref": "origin/main", "files": [], "skills": []}
        cfg = config.merge(config.DEFAULTS, {})
        found = {MONOREPO: {"path": "/w/iprally", "source": "detected"}, GITOPS: {"error": "bad root"}}
        got = {p["repo"]: p for p in projects.listing([pr(1, MINE), pr(2, SITE)], cfg, found, names)}
        self.assertEqual(asked, [(MONOREPO, "/w/iprally")])
        self.assertEqual([got[r]["conventions"] is None for r in (MONOREPO, GITOPS, MINE, SITE)], [False, True, True, True])

    def test_gates_are_default_until_the_owner_overrides_them(self):
        listed = lambda over: {p["repo"]: p["gates"] for p in projects.listing([pr(1, MINE)], config.merge(
            config.DEFAULTS, {"projects": over}), {})}
        self.assertEqual(listed({})[MONOREPO], [{"name": "cljfmt", "kind": "format", "source": "default"},
                                                {"name": "Karma", "kind": "test", "source": "default"}])
        self.assertEqual(listed({})[MINE], [])
        mine = {"fix": {"gates": [{"name": "pytest", "kind": "test", "run": "pytest"}]}}
        self.assertEqual(listed({MINE: mine})[MINE], [{"name": "pytest", "kind": "test", "source": "config"}])
        self.assertEqual(listed({MONOREPO: mine})[MONOREPO], [{"name": "pytest", "kind": "test", "source": "config"}])


class Checkouts(unittest.TestCase):
    def test_it_scans_again_after_a_roots_change_or_a_minute_while_a_wanted_repo_is_missing(self):
        scans = []
        checkouts = projects.Checkouts(lambda roots: scans.append(roots) or {MONOREPO: "/w/iprally"})
        cfg = config.merge(config.DEFAULTS, {})
        for wanted in ((), (MONOREPO,), (SITE,)):
            checkouts.get(cfg, wanted)
        self.assertEqual(len(scans), 1)
        with patch.object(projects.time, "monotonic", return_value=checkouts.at + projects.RETRY + 1):
            checkouts.get(cfg, (MONOREPO,))
            self.assertEqual(len(scans), 1)
            checkouts.get(cfg, (SITE,))
        self.assertEqual(len(scans), 2)
        checkouts.get(config.merge(cfg, {"detect": {"roots": ["~/src"]}}))
        self.assertEqual(scans[-1], ["~/src"])


class Lanes(unittest.TestCase):
    def test_a_tick_works_only_the_projects_with_a_checkout(self):
        handled = []
        with patch.object(rq, "queue", return_value=[pr(1), pr(2, SITE)]), \
                patch.object(rq, "handle", lambda p, *_: handled.append(rq.pr_key(p))), \
                patch.object(rq, "bumps", return_value={}), contextlib.redirect_stdout(io.StringIO()):
            rq.tick(None, True)
        self.assertEqual(handled, [(MONOREPO, 1)])

    def test_a_pr_without_a_checkout_has_no_lane(self):
        self.assertTrue(rq.unreviewed(pr(2, SITE)) and rq.unfixed(pr(2, SITE)))
        self.assertFalse(rq.fixable(pr(2, SITE), {}, {}))
        self.assertEqual(rq.row(pr(2, SITE), {}, {}, []), (4, "skipped", "no checkout"))
