#!/usr/bin/env python3
"""Install PR Loop: check the tools, link the repo into $HOME, start the daemon, build and open the app."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
from datetime import datetime
from xml.sax.saxutils import escape


CONFIG_SOURCE = ".pr-loop/config.json"
APP = "/Applications/PR Loop.app"
TOOLS = {"python3": "brew install python", "git": "xcode-select --install", "gh": "brew install gh",
         "claude": "https://claude.com/claude-code", "codex": "npm install -g @openai/codex"}


def default_config():
    spec = importlib.util.spec_from_file_location("pr_loop_config", Path(__file__).parent / "daemon/pr_loop/config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return json.dumps(module.DEFAULTS, indent=2) + "\n"


def render(template, home):
    return template.replace("{{ .chezmoi.homeDir }}", escape(str(home)))


def problems(path, app):
    """What blocks the daemon or the app. The daemon finds every tool on `path`, its plist PATH, not the shell's."""
    found = {tool: shutil.which(tool, path=path) for tool in TOOLS}
    for tool, hint in TOOLS.items():
        elsewhere = None if found[tool] else shutil.which(tool)
        if elsewhere:
            yield f"{tool} is off the daemon PATH: mkdir -p ~/.local/bin && ln -s {elsewhere} ~/.local/bin/"
        elif not found[tool]:
            yield f"{tool} is missing: {hint}"
    version = "import sys; sys.exit(sys.version_info < (3, 10))"
    if found["python3"] and subprocess.run([found["python3"], "-c", version]).returncode:
        yield f"{found['python3']} is older than 3.10: brew install python"
    if found["gh"] and subprocess.run([found["gh"], "auth", "status"], capture_output=True).returncode:
        yield "gh is not logged in: gh auth login"
    if not app:
        return
    if subprocess.run(["xcode-select", "-p"], capture_output=True).returncode:
        yield "the app needs the Command Line Tools: xcode-select --install (or --no-app)"
    macos = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.strip()
    if int(macos.split(".")[0]) < 26:
        yield f"the app needs macOS 26, this is {macos}: run with --no-app"


def chezmoi_source():
    if not shutil.which("chezmoi"):
        return None
    source = subprocess.run(["chezmoi", "source-path"], capture_output=True, text=True).stdout.strip()
    return Path(source) if source and Path(source).is_dir() else None


def start(plist, label, dry_run):
    """Bootstrap the daemon, or boot it out first when loaded, so a changed plist and new code both take effect."""
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    loaded = lambda: subprocess.run(["launchctl", "print", service], capture_output=True).returncode == 0
    print(f"{'Restart' if loaded() else 'Start'} {service}")
    if dry_run:
        return
    if loaded():
        subprocess.run(["launchctl", "bootout", service], check=True)
        while loaded():
            time.sleep(0.2)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)


def install_app(root, dry_run):
    print(f"Build {APP}, then open it")
    if not dry_run:
        subprocess.run([str(root / "ui/script/install")], check=True)
        subprocess.run(["open", APP], check=True)


def chezmoi_name(relative):
    parts = ["dot_" + part[1:] if part.startswith(".") else part for part in relative.parts]
    return Path(*parts[:-1]), parts[-1]


def install(root, home, chezmoi=None, dry_run=False):
    root, home = Path(root).resolve(), Path(home).resolve()
    chezmoi = Path(chezmoi).resolve() if chezmoi else None
    manifest = json.loads((root / "links.json").read_text())
    links = {home / target: root / source for target, source in manifest["links"].items()}
    templates = manifest.get("templates", {})
    for target, source in templates.items():
        links[home / target] = root / ".local" / Path(target).name
    for source in [*(root / p for p in manifest["links"].values()),
                   *(root / p for p in templates.values())]:
        if not source.exists():
            raise FileNotFoundError(source)
    backup = home / ".local/state" / root.name / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def preserve(path, relative):
        if path.exists() or path.is_symlink():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            path.rename(saved)
            print(f"Back up {path} -> {saved}")

    if not dry_run:
        for target, source in templates.items():
            rendered = links[home / target]
            rendered.parent.mkdir(parents=True, exist_ok=True)
            rendered.write_text(render((root / source).read_text(), home))

    for target, source in links.items():
        print(f"Link {target} -> {source}")
        if dry_run:
            continue
        if chezmoi:
            relative = target.relative_to(home)
            parent, name = chezmoi_name(relative)
            parent = chezmoi / parent
            managed = parent / f"symlink_{name}.tmpl"
            for variant in (name, name + ".tmpl", "executable_" + name, "executable_" + name + ".tmpl"):
                preserve(parent / variant, Path("chezmoi") / (parent / variant).relative_to(chezmoi))
            value = str(source)
            if source.is_relative_to(home):
                value = "{{ .chezmoi.homeDir }}/" + source.relative_to(home).as_posix()
            if not managed.exists() or managed.read_text() != value + "\n":
                preserve(managed, Path("chezmoi") / managed.relative_to(chezmoi))
                parent.mkdir(parents=True, exist_ok=True)
                managed.write_text(value + "\n")
        if target.is_symlink() and target.resolve() == source.resolve():
            continue
        preserve(target, Path("home") / target.relative_to(home))
        if not chezmoi:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.path.relpath(source, target.parent), target_is_directory=source.is_dir())

    config = home / manifest["config"] if "config" in manifest else None
    if config:
        print(f"Config {config}" + (f" -> {chezmoi / CONFIG_SOURCE}" if chezmoi else ""))
    if config and not dry_run:
        real = chezmoi / CONFIG_SOURCE if chezmoi else config
        if not real.exists():
            real.parent.mkdir(parents=True, exist_ok=True)
            real.write_text(default_config())
        if chezmoi:
            parent, name = chezmoi_name(config.relative_to(home))
            managed = chezmoi / parent / f"symlink_{name}.tmpl"
            value = "{{ .chezmoi.sourceDir }}/" + CONFIG_SOURCE + "\n"
            if not managed.exists() or managed.read_text() != value:
                preserve(managed, Path("chezmoi") / managed.relative_to(chezmoi))
                managed.parent.mkdir(parents=True, exist_ok=True)
                managed.write_text(value)
            if not (config.is_symlink() and config.resolve() == real.resolve()):
                preserve(config, Path("home") / config.relative_to(home))

    if chezmoi and not dry_run:
        subprocess.run(["chezmoi", "--source", str(chezmoi), "--destination", str(home), "--include", "files,dirs,symlinks",
                        "apply", "--force", "--parent-dirs", *(str(p) for p in [*links, *([config] if config else [])])],
                       check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="destination home directory")
    parser.add_argument("--chezmoi-source", type=Path, help="chezmoi source to update (default: `chezmoi source-path`)")
    parser.add_argument("--no-chezmoi", action="store_true", help="link straight into $HOME even with chezmoi set up")
    parser.add_argument("--no-app", action="store_true", help="skip building and opening PR Loop.app")
    parser.add_argument("--dry-run", action="store_true", help="print each step without changing anything")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    target, template = next(iter(json.loads((root / "links.json").read_text())["templates"].items()))
    daemon = plistlib.loads(render((root / template).read_text(), args.home).encode())
    blockers = list(problems(daemon["EnvironmentVariables"]["PATH"], not args.no_app))
    if blockers:
        sys.exit("Fix these, then run install.py again:\n" + "\n".join(f"  - {b}" for b in blockers))
    chezmoi = None if args.no_chezmoi else args.chezmoi_source or chezmoi_source()
    if chezmoi:
        print(f"Chezmoi source {chezmoi}")
    install(root, args.home, chezmoi, args.dry_run)
    start(args.home / target, daemon["Label"], args.dry_run)
    if not args.no_app:
        install_app(root, args.dry_run)
    if not shutil.which("pr-loop"):
        print("Add ~/.local/bin to your shell PATH to run pr-loop")
