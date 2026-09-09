"""Read and rewrite APP_VERSION in installer/AutoPara.nsi.

The .nsi is the single source of the version -- it names the OutFile, VIProductVersion and the
Add/Remove Programs entry -- and CI reads it with one specific regex. A hand-edit that breaks that
regex does not fail loudly; the build just throws late. So the rewrite is scripted and verified
against the same pattern the workflow uses.

Deciding *which* number to move is not scripted, and shouldn't be: that is a judgement about what
changed. This only does the mechanical part, then reports every other file still carrying the old
number so the caller can judge each one (a changelog entry about 1.2.0 must not be rewritten just
because 1.2.0 was the version we are leaving).

    python bump_version.py --show
    python bump_version.py --set 1.5.0
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The exact pattern .github/workflows/installer.yml matches. Keep them identical: a bump this
# script is happy with but the workflow cannot read is the failure mode worth designing out.
DEFINE_RE = re.compile(r'(?m)^!define\s+APP_VERSION\s+"([^"]+)"')

# ``.claude`` is agent tooling and never ships in the installer, so a version number written there
# (this skill's own examples, for one) is not a mention that needs rewriting -- and reporting it
# every run would teach the reader to skim a list that is supposed to be short and all-signal.
SKIP_DIRS = {".git", ".claude", ".venv", "venv", "build", "dist", "__pycache__", "node_modules"}
TEXT_SUFFIXES = {".md", ".nsi", ".py", ".ps1", ".cmd", ".yml", ".yaml", ".txt", ".cfg", ".ini"}


def repo_root() -> Path:
    """The working tree root, so the script runs from anywhere."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path(__file__).resolve().parents[4]


def nsi_path(root: Path) -> Path:
    path = root / "installer" / "AutoPara.nsi"
    if not path.is_file():
        sys.exit(f"not found: {path}")
    return path


def current_version(root: Path) -> str:
    match = DEFINE_RE.search(nsi_path(root).read_text(encoding="utf-8"))
    if not match:
        sys.exit("APP_VERSION not found in installer/AutoPara.nsi -- the file or the define moved")
    return match.group(1)


def already_released(tag: str) -> str:
    """Whether ``tag`` is taken, and by what. CI gates on the release, not the tag."""
    verdicts = []
    try:
        tags = subprocess.run(
            ["git", "tag", "-l", tag], capture_output=True, text=True, check=True
        ).stdout.split()
        if tags:
            verdicts.append("a git tag exists")
    except (subprocess.CalledProcessError, FileNotFoundError):
        verdicts.append("git tag lookup failed")
    try:
        probe = subprocess.run(
            ["gh", "release", "view", tag], capture_output=True, text=True
        )
        if probe.returncode == 0:
            verdicts.append("a GitHub release exists -- CI will NOT cut another")
    except FileNotFoundError:
        verdicts.append("gh not installed, release state unknown")
    return "; ".join(verdicts) if verdicts else "free"


def bumped(version: str) -> dict[str, str]:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return {}
    major, minor, patch = (int(part) for part in parts)
    return {
        "patch": f"{major}.{minor}.{patch + 1}",
        "minor": f"{major}.{minor + 1}.0",
        "major": f"{major + 1}.0.0",
    }


def other_mentions(root: Path, version: str) -> list[tuple[Path, int, str]]:
    """Every line outside the .nsi still naming ``version``."""
    hits: list[tuple[Path, int, str]] = []
    nsi = nsi_path(root)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path == nsi or SKIP_DIRS & set(part for part in path.relative_to(root).parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if version in line:
                hits.append((path.relative_to(root), number, line.strip()))
    return hits


def show(root: Path) -> None:
    version = current_version(root)
    print(f"APP_VERSION       {version}")
    print(f"tag v{version}       {already_released(f'v{version}')}")
    for part, candidate in bumped(version).items():
        print(f"  next {part:<5}      {candidate}   (v{candidate}: {already_released(f'v{candidate}')})")
    mentions = other_mentions(root, version)
    print(f"\n{len(mentions)} other line(s) name {version}:")
    for path, number, line in mentions:
        print(f"  {path}:{number}  {line[:100]}")


def apply(root: Path, new: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        sys.exit(f"'{new}' is not a three-part version -- NSIS VIProductVersion appends a fourth")
    old = current_version(root)
    if new == old:
        sys.exit(f"already {old}; nothing to do")

    path = nsi_path(root)
    text = path.read_text(encoding="utf-8")
    updated = DEFINE_RE.sub(lambda m: m.group(0).replace(f'"{old}"', f'"{new}"'), text, count=1)
    path.write_text(updated, encoding="utf-8")

    check = DEFINE_RE.search(path.read_text(encoding="utf-8"))
    if not check or check.group(1) != new:
        sys.exit("rewrite did not take -- the workflow regex no longer reads this file")
    print(f"installer/AutoPara.nsi  APP_VERSION {old} -> {new}")

    mentions = other_mentions(root, old)
    if not mentions:
        print("\nNo other file named the old version. Nothing else to do.")
        return
    print(f"\n{len(mentions)} line(s) still name {old} -- decide each one:")
    for mention_path, number, line in mentions:
        print(f"  {mention_path}:{number}  {line[:100]}")
    print(
        "\nRewrite the ones that describe the version being shipped now (the README's build-output\n"
        "table names the file the build writes). Leave anything that is a record of a past release."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="report the version and release state")
    parser.add_argument("--set", dest="new", help="rewrite APP_VERSION to this version")
    args = parser.parse_args()

    root = repo_root()
    if args.new:
        apply(root, args.new)
    else:
        show(root)


if __name__ == "__main__":
    main()
