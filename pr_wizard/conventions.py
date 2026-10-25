"""A project's own conventions, read from its checkout and rendered as the `{CONVENTIONS}` block (api.md §4.8)."""
import fnmatch
import glob
import os
import re
import subprocess
from dataclasses import dataclass, field

AGENT_FILES = ("AGENTS.md", "CLAUDE.md")
CONTRIBUTING = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
CONFIGS = (".cljfmt.edn", "cljfmt.edn", ".clj-kondo/config.edn", ".prettierrc*", "prettier.config.*", ".eslintrc*",
           "eslint.config.*", "biome.json", ".stylelintrc*", "ruff.toml", ".ruff.toml", "pyproject.toml", ".flake8",
           "rustfmt.toml", ".rustfmt.toml", ".golangci.yml", ".rubocop.yml", ".swiftformat", ".swift-format",
           ".swiftlint.yml")
PYPROJECT_TABLES = ("tool.ruff", "tool.black", "tool.isort")
SKILLS = (".agents/skills", ".claude/skills")
INCLUDE = re.compile(r"^@(\S+)$")
SKILL_BLOCK = re.compile(r"^\{SKILL (\S+)\}\n(.*?)^\{/SKILL\}\n", re.M | re.S)
TABLE = re.compile(r"^\[\[?([^\]]+)\]\]?")
INCLUDE_DEPTH = 3
DOC_CAP = 12 * 1024
TOTAL_CAP = 32 * 1024
INLINE_CONFIG = 2 * 1024
NONE = ('<conventions none="true">This project documents no conventions. Judge the change against the code around '
        'it, and report no convention findings.</conventions>')


@dataclass
class Conventions:
    files: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    text: str = NONE

    @property
    def none(self):
        return not self.files and not self.skills

    def skill(self, name):
        return next((s["path"] for s in self.skills if s["name"] == name), None)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def inside(root, path):
    return os.path.commonpath([root, path]) == root


def expand(root, path, seen, files, depth=0):
    """`path` with each `@file` line replaced by that file, relative to `path`, at most INCLUDE_DEPTH deep and only
    inside the checkout. A file already in `seen` is not repeated."""
    lines = []
    for line in read(path).splitlines():
        if not (m := INCLUDE.match(line.strip())):
            lines.append(line)
            continue
        target = os.path.realpath(os.path.join(os.path.dirname(path), m[1]))
        if (depth < INCLUDE_DEPTH and not m[1].startswith("~") and inside(root, target) and target not in seen
                and os.path.isfile(target)):
            seen.add(target)
            files.append(os.path.relpath(target, root))
            lines.append(expand(root, target, seen, files, depth + 1))
    return "\n".join(lines).strip()


def nested(changed_paths):
    """The AGENTS.md / CLAUDE.md candidates above each changed path, closest first, root excluded."""
    found = []
    for path in changed_paths:
        d = os.path.dirname(path)
        while d:
            found += [f"{d}/{name}" for name in AGENT_FILES]
            d = os.path.dirname(d)
    return list(dict.fromkeys(found))


def pyproject_tables(text):
    keep, out = False, []
    for line in text.splitlines():
        if m := TABLE.match(line):
            keep = any(m[1].strip() == t or m[1].strip().startswith(t + ".") for t in PYPROJECT_TABLES)
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def configs(root):
    """(path, text) of every formatter and linter config at the checkout root, in the CONFIGS order."""
    paths = dict.fromkeys(os.path.relpath(p, root) for pattern in CONFIGS
                          for p in sorted(glob.glob(os.path.join(root, pattern))) if os.path.isfile(p))
    found = [(p, read(os.path.join(root, p))) for p in paths]
    return [(p, t) for p, t in ((p, pyproject_tables(t) if p == "pyproject.toml" else t) for p, t in found) if t]


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    meta, key = {}, None
    for line in text.splitlines()[1:]:
        if line.startswith("---"):
            break
        if (m := re.match(r"^(\w[\w-]*):\s*(.*)$", line)):
            key, value = m[1], m[2].strip()
            meta[key] = "" if value in (">", "|", ">-", "|-") else value.strip("\"'")
        elif key and line.startswith((" ", "\t")):
            meta[key] = f"{meta[key]} {line.strip()}".strip()
    return meta


def skills(root):
    found = {}
    for base in SKILLS:
        for path in sorted(glob.glob(os.path.join(root, base, "*", "SKILL.md"))):
            real = os.path.realpath(path)
            if real not in found:
                meta = frontmatter(read(path))
                found[real] = {"name": meta.get("name") or os.path.basename(os.path.dirname(path)),
                               "description": meta.get("description", ""), "path": os.path.relpath(path, root)}
    return list(found.values())


def collect(worktree, changed_paths):
    """The conventions of the checkout at `worktree` for a change to `changed_paths`, in the §4.8 order."""
    root = os.path.realpath(worktree)
    seen, files, docs = set(), [], []
    contributing = next((p for p in CONTRIBUTING if os.path.isfile(os.path.join(root, p))), None)
    for rel in [*AGENT_FILES, *nested(changed_paths), *([contributing] if contributing else []), ".editorconfig"]:
        path = os.path.join(root, rel)
        real = os.path.realpath(path)
        if os.path.isfile(path) and real not in seen:
            seen.add(real)
            files.append(rel)
            docs.append((rel, expand(root, real, seen, files) if os.path.basename(rel) in AGENT_FILES else read(real)))
    listed = []
    for rel, text in configs(root):
        files.append(rel)
        (docs if len(text) <= INLINE_CONFIG else listed).append((rel, text))
    conv = Conventions(files, skills(root))
    if not conv.none:
        conv.text = render(docs, listed, conv.skills)
    return conv


def render(docs, listed, skill_list):
    budget, sections, capped = TOTAL_CAP, [], []
    for rel, text in docs:
        if not text.strip():
            continue
        if budget <= 0:
            capped.append(rel)
            continue
        cut = text[:min(DOC_CAP, budget)]
        budget -= len(cut)
        sections.append(f"### {rel}\n\n{cut}" + (f"\n[… truncated: read {rel} for the rest]" if cut != text else ""))
    lines = [*sections]
    if capped:
        lines.append("Over the size cap, read when they apply: " + ", ".join(f"`{p}`" for p in capped))
    if listed:
        lines.append("Formatter and linter configs, read when they apply: " + ", ".join(f"`{p}`" for p, _ in listed))
    if skill_list:
        lines.append("Project skills:\n" + "\n".join(
            f"- `{s['path']}`" if budget <= 0 else f"- {s['name']} — {s['description']} (`{s['path']}`)"
            for s in skill_list))
    return "<conventions>\n" + "\n\n".join(lines) + "\n</conventions>"


def names(root, ref):
    """{ref, files, skills} as found at `ref` of the checkout at `root`, by tree names only: the root sources, every
    AGENTS.md / CLAUDE.md up to 2 levels deep, and the skill names."""
    tree = subprocess.run(["git", "-C", root, "ls-tree", "-r", "--name-only", ref], capture_output=True, text=True,
                          check=True).stdout.splitlines()
    have = set(tree)
    deep = sorted(p for p in tree if os.path.basename(p) in AGENT_FILES and 1 <= p.count("/") <= 2)
    contributing = next((p for p in CONTRIBUTING if p in have), None)
    pyproject = "pyproject.toml" in have and pyproject_tables(subprocess.run(
        ["git", "-C", root, "show", f"{ref}:pyproject.toml"], capture_output=True, text=True).stdout)
    conf = [p for c in CONFIGS for p in sorted(fnmatch.filter(tree, c)) if p != "pyproject.toml" or pyproject]
    skill_names = sorted({p.split("/")[2] for p in tree
                          if p.startswith(tuple(f"{s}/" for s in SKILLS)) and p.count("/") == 3
                          and p.endswith("/SKILL.md")})
    files = [p for p in AGENT_FILES if p in have] + deep + ([contributing] if contributing else []) + \
        [p for p in (".editorconfig",) if p in have] + list(dict.fromkeys(conf))
    return {"ref": ref, "files": files, "skills": skill_names}


def fill(prompt, conv):
    """`prompt` with `{CONVENTIONS}` rendered, and each `{SKILL name}…{/SKILL}` block kept, with `{PATH}` set to the
    skill's SKILL.md, only when the project lists that skill."""
    keep = lambda m: m[2].replace("{PATH}", conv.skill(m[1])) if conv.skill(m[1]) else ""
    return SKILL_BLOCK.sub(keep, prompt).replace("{CONVENTIONS}", conv.text)
