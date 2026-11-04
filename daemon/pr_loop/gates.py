"""The fixer gates (api.md §4.9): a project's own format and test commands, run after Codex in its worktree."""

import fcntl
import fnmatch
import os
import re
import shlex
import shutil
import signal
import subprocess
import textwrap
import time
from contextlib import contextmanager, nullcontext

from pr_loop import names

SLOTS = 2
WIDTH = 96
NO_GATES = ("The caller runs no checks after you. Run the formatter, linter and tests that the conventions name, "
            "when they work offline in this sandbox.")


def argv(cmd):
    """A plain word list runs as is, which is what `bash -c` would exec; anything else runs through bash."""
    words = shlex.split(cmd)
    return words if shlex.join(words) == cmd else ["bash", "-c", cmd]


def line(gate, cmd):
    return f"{gate['prelude']} && {cmd}" if "prelude" in gate else cmd


def render(cmd, files, item=None):
    return cmd.replace("{files}", shlex.join(files)).replace("{item}", shlex.quote(item or ""))


def cwd(gate, wt):
    return os.path.join(wt, gate["cwd"]) if "cwd" in gate else wt


def matching(gate, paths):
    return [p for p in paths if any(fnmatch.fnmatchcase(p, glob) for glob in gate["when"])]


def items(gate, wt, files):
    """The targets of a test gate: each path rewritten by `map`, kept when it matches `keep`, its group 1 the item."""
    t = gate["targets"]
    found = set()
    for path in files:
        for pattern, repl in t.get("map", []):
            path = re.sub(pattern, repl, path)
        kept = re.fullmatch(t.get("keep", "(.*)"), path)
        if kept and (not t.get("exists") or os.path.exists(os.path.join(wt, path))):
            item = kept[1]
            for a, b in t.get("item", {}).items():
                item = item.replace(a, b)
            found.add(item)
    return sorted(i for i in found if "valid" not in t or re.fullmatch(t["valid"], i))


def execute(gate, wt, cmd):
    """A timeout is a red run, so the pass saves its work; the group kill takes the JVMs under bash too."""
    proc = subprocess.Popen(argv(line(gate, cmd)), cwd=cwd(gate, wt), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        log = proc.communicate(timeout=gate.get("timeout_s"))[0]
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        log = proc.communicate()[0] + f"\n{cmd} timed out after {gate['timeout_s']} s"
    return {"ok": proc.returncode == 0, "log": log}


@contextmanager
def slot():
    """One of SLOTS across every run on this machine: for gates that are cold JVM builds or browsers."""
    os.makedirs(names.LOOP, exist_ok=True)
    while True:
        for i in range(SLOTS):
            with open(names.slot(i), "w") as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                yield
                return
        time.sleep(15)


def test(gate, wt, files):
    """One `setup`, then one run per item; without `targets`, one run named after the gate."""
    targets = items(gate, wt, files) if "targets" in gate else [gate["name"]]
    entry = lambda ns, result: {"gate": gate["name"], "ns": ns, **result}
    missing = next((p for p in gate.get("needs", []) if not os.path.exists(os.path.join(wt, p))), None)
    if not targets or missing:
        return [entry(ns, {"ok": None, "log": f"{missing} missing, CI grades it"}) for ns in targets]
    with slot() if gate.get("slot") else nullcontext():
        if "setup" in gate:
            built = execute(gate, wt, render(gate["setup"]["run"], files))
            if not built["ok"]:
                return [entry(gate["setup"]["name"], built)]
        return [entry(ns, execute(gate, wt, render(gate["run"], files, ns if "targets" in gate else None)))
                for ns in targets]


def run(gates, wt, paths):
    """Every gate in order: format gates fix the files in place, test gates return `{gate, ns, ok, log}` per item."""
    results = []
    for gate in gates:
        files = matching(gate, paths)
        if not files or ("requires" in gate and not shutil.which(gate["requires"])):
            continue
        if gate["kind"] == "format":
            subprocess.run(argv(line(gate, render(gate["run"], files))), cwd=cwd(gate, wt), capture_output=True)
        else:
            results += test(gate, wt, files)
    return results


def fill(prompt, gates):
    """`prompt` with `{GATES}` rendered from each gate's `note`, its list item re-wrapped."""
    text = " ".join(g["note"] for g in gates if "note" in g) if gates else NO_GATES
    wrap = lambda m: textwrap.fill(m[0].replace("{GATES}", text), WIDTH,
                                   subsequent_indent=" " * re.match(r"\s*(?:\d+\.|[-*])?\s*", m[0]).end())
    return re.sub(r"^.*\{GATES\}.*$", wrap, prompt, flags=re.M)


def retry(gates, red, logs):
    """The Codex turn that hands the red runs back, with the files of those gates it must not edit."""
    failed = [g for g in gates if g["name"] in {t["gate"] for t in red}]
    protect = list(dict.fromkeys(p for g in failed for p in g.get("protect", [])))
    return (f"These {' and '.join(g['name'] for g in failed)} runs fail after your change:\n\n{logs}\n\n"
            "Read each full log first: the cause is often above the tail. Fix what your change broke. "
            + (f"Never edit build or runner config ({', '.join(protect)}) to make a run pass. " if protect else "")
            + "When the build or the runner fails and your change does not cause it, change nothing and say so "
            "in `summary`. Return the same JSON as before, for the same refs.")
