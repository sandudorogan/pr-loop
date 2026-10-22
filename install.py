#!/usr/bin/env python3
"""Install repository files at their existing paths through symlinks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime
from xml.sax.saxutils import escape


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
            rendered.write_text((root / source).read_text().replace("{{ .chezmoi.homeDir }}", escape(str(home))))

    for target, source in links.items():
        print(f"Link {target} -> {source}")
        if dry_run:
            continue
        if chezmoi:
            relative = target.relative_to(home)
            parts = ["dot_" + part[1:] if part.startswith(".") else part for part in relative.parts]
            parent, name = chezmoi.joinpath(*parts[:-1]), parts[-1]
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

    if chezmoi and not dry_run:
        subprocess.run(["chezmoi", "--source", str(chezmoi), "--destination", str(home), "--include", "files,dirs,symlinks",
                        "apply", "--force", "--parent-dirs", *(str(p) for p in links)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="destination home directory")
    parser.add_argument("--chezmoi-source", type=Path, help="update this source and apply only the owned paths")
    parser.add_argument("--dry-run", action="store_true", help="print links without changing files")
    args = parser.parse_args()
    install(Path(__file__).resolve().parent, args.home, args.chezmoi_source, args.dry_run)
