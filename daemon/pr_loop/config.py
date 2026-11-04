"""The PR Loop config (api.md §4): defaults, merge, validation, effective config, atomic save."""

import copy
import hashlib
import json
import os
import re
from typing import Any, Callable, NamedTuple

from pr_loop import db

NO_REVIEW, NO_FIX = "no-auto-review", "no-auto-fix"
ENGINES, FIX_ENGINES, GATE_KINDS = ["claude", "codex"], ["codex"], ["format", "test"]
CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
CODEX_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]
CLAUDE_MODELS = ["opus", "sonnet", "haiku"]
PROMPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "review", "prompts")
CODEX_HOME = os.path.expanduser("~/.codex")

DEFAULTS = json.loads(r'''
{
  "version": 1,
  "detect": {"roots": ["~/workdir"]},
  "lanes": {"separate": false},
  "projects": {
    "iprally/iprally": {"fix": {"gates": [
      {"name": "cljfmt", "kind": "format", "when": ["*.clj", "*.cljs", "*.cljc", "*.edn"], "requires": "cljfmt",
       "run": "cljfmt fix {files}"},
      {"name": "Karma", "kind": "test", "when": ["ui/src/cljs/*.cljs", "ui/test/*_test.cljs"], "cwd": "ui",
       "prelude": ". ~/.config/nvm/nvm.sh && nvm use 22.15.1 >/dev/null", "needs": ["ui/node_modules"],
       "targets": {"map": [["^ui/src/cljs/(.+)\\.cljs$", "ui/test/\\1_test.cljs"]], "keep": "^ui/test/(.+_test)\\.cljs$",
                   "exists": true, "item": {"/": ".", "_": "-"}, "valid": "^[\\w.-]+$"},
       "setup": {"name": "shadow-cljs compile karma-test",
                 "run": "(cd .. && npm run postinstall) && npx shadow-cljs compile karma-test"},
       "run": "npx karma start --single-run --client.args iprally_ui.karma_runner_test.init --client.args {item}",
       "timeout_s": 1800, "slot": true, "protect": ["shadow-cljs.edn", "karma.conf.js", "package.json"],
       "note": "Do not run tests that need a JVM or a browser (lein, Karma): they abort in this sandbox. The caller runs the Karma namespaces you touch after you finish and sends any failure back to you."}
    ]}},
    "iprally/gitops": {"review": {"enabled": false}}
  },
  "review": {
    "enabled": true,
    "workers": 3,
    "rounds": 8,
    "max_added": 4000,
    "trivial": ["*.lock", "*lock.json", "*.lockb", "*.md", "*.png", "*.jpg", "*.svg"],
    "timeout_s": 2700,
    "reviewers": [
      {"id": "opus", "enabled": true, "label": "Claude Opus 5.5", "prompt": "opus.md",
       "engine": "claude", "fallback": true, "needs_conventions": false, "advisory": false,
       "claude": {"model": "opus", "effort": "high", "incremental": {"model": "opus", "effort": "medium"}},
       "codex": {"model": null, "effort": null}},
      {"id": "codex", "enabled": true, "label": "Codex", "prompt": "codex.md",
       "engine": "codex", "fallback": true, "needs_conventions": false, "advisory": false,
       "claude": {"model": "opus", "effort": null, "incremental": null},
       "codex": {"model": null, "effort": null}},
      {"id": "quality", "enabled": true, "label": "Claude Haiku 5.5 · quality self-review", "prompt": "quality.md",
       "engine": "claude", "fallback": true, "needs_conventions": true, "advisory": true,
       "claude": {"model": "haiku", "effort": "xhigh", "incremental": null},
       "codex": {"model": null, "effort": null}}
    ]
  },
  "fix": {
    "enabled": true,
    "workers": 3,
    "engine": "codex",
    "model": null,
    "effort": null,
    "prompt": "fix.md",
    "merge_prompt": "merge.md",
    "turn_timeout_s": 2700,
    "pass_timeout_s": 14400,
    "max_errors": 3,
    "test_retries": 2,
    "ci_tries": 3,
    "ci_apps": ["github-actions"],
    "gates": []
  },
  "refresh": {"interval_s": 300, "idle_s": 60}
}
''')


# ---------------------------------------------------------------- merge

def merge(base, over):
    """Objects merge, everything else (arrays, scalars, null) replaces. Inputs stay untouched."""
    if not (isinstance(base, dict) and isinstance(over, dict)):
        return copy.deepcopy(over)
    return {k: merge(base[k], over[k]) if k in base and k in over else copy.deepcopy(over[k] if k in over else base[k])
            for k in {**base, **over}}


def merge_patch(base, patch):
    """RFC 7396: like `merge`, but a null in the patch deletes the key."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = merge_patch(out.get(key), value)
    return out


def rev(doc):
    return hashlib.sha1(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- validation

class Leaf(NamedTuple):
    ok: Callable[[Any], bool]
    expect: str


class Opt(NamedTuple):
    spec: Any


class Arr(NamedTuple):
    item: Any
    lo: int = 0
    hi: int = 10**6


class Obj(NamedTuple):
    fields: dict
    required: tuple = ()


class Keyed(NamedTuple):
    key: re.Pattern
    value: Any
    hi: int


def regex_ok(v):
    try:
        re.compile(v)
        return True
    except (re.error, TypeError):
        return False


def string(v):
    return isinstance(v, str) and v != ""


def integer(lo, hi):
    return Leaf(lambda v: type(v) is int and lo <= v <= hi, f"an integer from {lo} to {hi}")


def one_of(options, null=False):
    return Leaf(lambda v: v in options or (null and v is None), f"one of {options}" + (" or null" if null else ""))


BOOL = Leaf(lambda v: isinstance(v, bool), "true or false")
TEXT = Leaf(string, "a non-empty string")
NULL_TEXT = Leaf(lambda v: v is None or string(v), "a non-empty string or null")
REGEX = Leaf(lambda v: string(v) and regex_ok(v), "a valid regex")
PROMPT = Leaf(lambda v: string(v) and v in prompts(), "a prompt in review/prompts")
PAIR = Leaf(lambda v: isinstance(v, list) and len(v) == 2 and all(map(string, v)) and regex_ok(v[0]),
            "[regex, replacement]")
CHARS = Leaf(lambda v: isinstance(v, dict) and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()),
             "an object of strings")

CLAUDE_MODEL_EFFORT = Obj({"model": NULL_TEXT, "effort": one_of(CLAUDE_EFFORTS, null=True),
                           "incremental": Opt(Obj({"model": TEXT, "effort": one_of(CLAUDE_EFFORTS, null=True)},
                                                  ("model", "effort")))})
REVIEWER = Obj({
    "id": Leaf(lambda v: isinstance(v, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", v) is not None,
               "an id like ^[a-z][a-z0-9-]{0,31}$"),
    "enabled": BOOL, "label": Leaf(lambda v: isinstance(v, str) and 1 <= len(v) <= 80, "a string of 1-80 characters"),
    "prompt": PROMPT, "engine": one_of(ENGINES), "fallback": BOOL, "needs_conventions": BOOL, "advisory": BOOL,
    "claude": CLAUDE_MODEL_EFFORT, "codex": Obj({"model": NULL_TEXT, "effort": one_of(CODEX_EFFORTS, null=True)}),
}, ("id", "label", "prompt", "engine"))
TARGETS = Obj({"map": Arr(PAIR), "keep": REGEX, "exists": BOOL, "item": CHARS, "valid": REGEX})
GATE = Obj({
    "name": TEXT, "kind": one_of(GATE_KINDS), "when": Arr(TEXT, 1), "run": TEXT, "cwd": TEXT, "prelude": TEXT,
    "requires": TEXT, "needs": Arr(TEXT), "targets": TARGETS, "setup": Obj({"name": TEXT, "run": TEXT}, ("name", "run")),
    "timeout_s": integer(1, 86400), "slot": BOOL, "protect": Arr(TEXT), "note": TEXT,
}, ("name", "kind", "when", "run"))
REVIEW = Obj({
    "enabled": BOOL, "workers": integer(1, 8), "rounds": integer(1, 50), "max_added": integer(1, 100000),
    "trivial": Arr(TEXT, 1, 50), "timeout_s": integer(60, 14400), "reviewers": Arr(REVIEWER, 1, 8),
})
FIX = Obj({
    "enabled": BOOL, "workers": integer(1, 8), "engine": one_of(FIX_ENGINES), "model": NULL_TEXT,
    "effort": one_of(CODEX_EFFORTS, null=True), "prompt": PROMPT, "merge_prompt": PROMPT,
    "turn_timeout_s": integer(60, 14400), "pass_timeout_s": integer(600, 86400), "max_errors": integer(1, 10),
    "test_retries": integer(0, 5), "ci_tries": integer(1, 10), "ci_apps": Arr(TEXT), "gates": Arr(GATE, 0, 10),
})


def whole(fields):
    return Obj(fields, tuple(fields))


def without_workers(obj):
    return Obj({k: v for k, v in obj.fields.items() if k != "workers"})


CONFIG = whole({
    "version": Leaf(lambda v: v == 1 and type(v) is int, "1"),
    "detect": whole({"roots": Arr(TEXT, 1, 10)}), "lanes": whole({"separate": BOOL}),
    "projects": Keyed(re.compile(r"[\w.-]+/[\w.-]+"), Obj({"root": TEXT, "review": REVIEW, "fix": FIX}), 50),
    "review": whole(REVIEW.fields), "fix": whole(FIX.fields),
    "refresh": whole({"interval_s": integer(60, 3600), "idle_s": integer(15, 3600)}),
})
PR_LEVEL = Obj({"review": without_workers(REVIEW), "fix": without_workers(FIX)})


def prompts():
    try:
        return sorted(n for n in os.listdir(PROMPTS) if n.endswith(".md"))
    except OSError:
        return []


def problem(path, message):
    return {"path": path, "message": message}


def keyed(path, key):
    return f"{path}[{json.dumps(key)}]"


def walk(value, spec, path, out):
    if isinstance(spec, Opt):
        return value is None or walk(value, spec.spec, path, out)
    where = lambda key: f"{path}.{key}" if path else key
    if isinstance(spec, Leaf):
        spec.ok(value) or out.append(problem(path, f"must be {spec.expect}"))
    elif isinstance(spec, Arr):
        if not isinstance(value, list) or not spec.lo <= len(value) <= spec.hi:
            return out.append(problem(path, f"must be an array of {spec.lo}-{spec.hi} items"))
        [walk(item, spec.item, f"{path}[{i}]", out) for i, item in enumerate(value)]
    elif isinstance(spec, Keyed):
        if not isinstance(value, dict) or len(value) > spec.hi:
            return out.append(problem(path, f"must be an object of at most {spec.hi} entries"))
        for key, item in value.items():
            spec.key.fullmatch(key) or out.append(problem(keyed(path, key), "must be keyed owner/name"))
            walk(item, spec.value, keyed(path, key), out)
    elif not isinstance(value, dict):
        out.append(problem(path, "must be an object"))
    else:
        [out.append(problem(where(k), "unknown key")) for k in value if k not in spec.fields]
        [out.append(problem(where(k), "is required")) for k in spec.required if k not in value]
        [walk(v, spec.fields[k], where(k), out) for k, v in value.items() if k in spec.fields]


def reviewer_rules(reviewers, path, out):
    ids = [r["id"] for r in reviewers]
    [out.append(problem(f"{path}[{i}].id", "must be unique")) for i, x in enumerate(ids) if x in ids[:i]]
    for i, r in enumerate(reviewers):
        if (r["engine"] == "claude" or r.get("fallback", True)) and not string((r.get("claude") or {}).get("model")):
            out.append(problem(f"{path}[{i}].claude.model", "is required when the reviewer can run on claude"))


def effective_rules(eff, path, out):
    reviewers = eff["review"]["reviewers"]
    reviewer_rules(reviewers, f"{path}review.reviewers", out)
    if eff["review"]["enabled"] and not any(r.get("enabled", True) for r in reviewers):
        out.append(problem(f"{path}review.reviewers", "needs at least one enabled reviewer"))


def validate(doc, level="config", base=None):
    """Problems as `{path, message}`, empty when valid. Level "pr" takes a partial override: `review.*` and `fix.*`
    without `workers`, checked as merged over `base` (default: the defaults)."""
    out = []
    walk(doc, CONFIG if level == "config" else PR_LEVEL, "", out)
    if out:
        return out
    if level == "pr":
        effective_rules(merge(base or {k: DEFAULTS[k] for k in ("review", "fix")}, doc), "", out)
        return out
    top = {k: doc[k] for k in ("review", "fix")}
    effective_rules(top, "", out)
    [effective_rules(merge(top, p), f"{keyed('projects', name)}.", out) for name, p in doc["projects"].items()]
    if doc["refresh"]["idle_s"] > doc["refresh"]["interval_s"]:
        out.append(problem("refresh.idle_s", "must not exceed refresh.interval_s"))
    return out


# ---------------------------------------------------------------- load, save

def default_path():
    return os.environ.get("PR_LOOP_CONFIG") or os.path.expanduser("~/.config/pr-loop/config.json")


class Loaded(NamedTuple):
    config: dict
    source: str
    error: str | None
    path: str
    real_path: str
    rev: str


def load(path=None):
    """Never raises. A missing file gives the defaults. An unreadable or invalid one gives the defaults and an `error`."""
    path = path or default_path()
    config, source, error = copy.deepcopy(DEFAULTS), "defaults", None
    try:
        with open(path, encoding="utf-8") as fh:
            merged = merge(DEFAULTS, json.load(fh))
        problems = validate(merged) if isinstance(merged, dict) else [problem("", "must be an object")]
        error = next((f"{p['path']}: {p['message']}".removeprefix(": ") for p in problems), None)
        if not problems:
            config, source = merged, "file"
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        error = f"{type(e).__name__}: {e}"
    return Loaded(config, source, error, path, os.path.realpath(path), rev(config))


def save(config, path=None):
    """Temp file + rename beside the resolved real path, so a chezmoi symlink at `path` survives."""
    real = os.path.realpath(path or default_path())
    os.makedirs(os.path.dirname(real), exist_ok=True)
    tmp = f"{real}.tmp-{os.getpid()}"
    try:
        mode = os.stat(real).st_mode & 0o7777 if os.path.exists(real) else 0o644
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(config, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
            os.fchmod(fh.fileno(), mode)
        os.replace(tmp, real)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- effective

def effective(config, repo, pr_override=None, labels=()):
    """defaults ⊕ projects[repo] ⊕ PR override, then the labels, which can only turn a lane off."""
    eff = merge({k: config[k] for k in ("review", "fix")}, config["projects"].get(repo) or {})
    eff = merge(eff, pr_override or {})
    for label, lane in ((NO_REVIEW, "review"), (NO_FIX, "fix")):
        if label in labels:
            eff[lane]["enabled"] = False
    return eff


def effective_for(repo, number, labels=(), cfg=None):
    """`effective()` of one PR: the config file (or `cfg`), the PR's `pr_overrides` row and its labels. The daemon
    and both scripts call it, so a run by hand gets the config of a daemon run."""
    row = db.pr_override(repo, number)
    return effective(cfg or load().config, repo, row and row["config"], labels)


def paths(doc, prefix=""):
    """The leaf paths an override sets: objects descend, arrays and scalars are leaves."""
    return [p for k, v in doc.items() for p in (paths(v, f"{prefix}{k}.") if isinstance(v, dict) else [f"{prefix}{k}"])]


# ---------------------------------------------------------------- choices

def toml_top_level(path, *keys):
    found = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.lstrip().startswith("["):
                    break
                m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
                if m and m[1] in keys:
                    found[m[1]] = m[2]
    except OSError:
        pass
    return found


def choices(codex_home=None):
    """The picker lists for the app. The Codex lists are suggestions read from `~/.codex`; empty when unreadable."""
    home = codex_home or CODEX_HOME
    try:
        with open(os.path.join(home, "models_cache.json"), encoding="utf-8") as fh:
            models = [{"model": m["slug"], "efforts": [lv["effort"] for lv in m["supported_reasoning_levels"]],
                       "default_effort": m.get("default_reasoning_level")}
                      for m in json.load(fh)["models"] if m.get("visibility") != "hide"]
    except (OSError, ValueError, KeyError, TypeError):
        models = []
    top = toml_top_level(os.path.join(home, "config.toml"), "model", "model_reasoning_effort")
    return {
        "engines": ENGINES, "fix_engines": FIX_ENGINES, "gate_kinds": GATE_KINDS,
        "claude_efforts": CLAUDE_EFFORTS, "codex_efforts": CODEX_EFFORTS, "claude_models": CLAUDE_MODELS,
        "codex_default": {"model": top["model"], "effort": top.get("model_reasoning_effort")} if "model" in top else None,
        "codex_models": models, "prompts": prompts(),
    }
