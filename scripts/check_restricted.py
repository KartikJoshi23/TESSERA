#!/usr/bin/env python3
"""Commit guard for the public TESSERA repository.

Blocks, before anything can be committed or pushed:

* files that must stay on this machine: ``PS.md``, real register and alert data,
  DFSA hand-recorded facts, datasets, run logs and ``.env``;
* the restricted-content marker;
* deep links into ``dfsa.ae`` (the DFSA's terms allow links to its homepage only);
* API keys and private keys.

Usage::

    python scripts/check_restricted.py --staged      # git pre-commit hook (checks the index)
    python scripts/check_restricted.py --all         # CI (checks every tracked file)
    python scripts/check_restricted.py PATH [PATH…]  # check specific working-tree files

Standard library only, so it runs before any dependency is installed.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

# Paths (POSIX, relative to the repository root) that must never be committed.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "PS.md",
    ".env",
    ".env.*",
    "data/inbox/*",
    "data/snapshots/*",
    "data/restricted/*",
    "data/handrecords/*",
    "datasets/*",
    "runs/*",
)

# Exceptions to FORBIDDEN_PATHS: documentation and empty templates only.
ALLOWED_PATHS: tuple[str, ...] = (
    ".env.example",
    "data/handrecords/README.md",
    "data/handrecords/templates/*",
    "datasets/README.md",
)

# Written as two literals so that this file does not match its own check.
RESTRICTED_MARKER = "TESSERA-" "RESTRICTED"

# "dfsa.ae/" followed by a path character. The bare homepage ("https://www.dfsa.ae/") is allowed.
DFSA_DEEP_LINK = re.compile(r"dfsa\.ae/[A-Za-z0-9_\-%#?=&~][^\s)\"'<>\]`]*", re.IGNORECASE)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("NVIDIA API key", re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

# Files whose *content* legitimately contains the patterns above (as definitions or test inputs).
CONTENT_EXEMPT: tuple[str, ...] = (
    "scripts/check_restricted.py",
    "backend/tests/test_check_restricted.py",
)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def check_path(path: str) -> list[str]:
    """Return violations for a repository-relative POSIX path."""
    path = path.replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    if _matches(path, ALLOWED_PATHS):
        return []
    if _matches(path, FORBIDDEN_PATHS):
        return [f"{path}: this path must stay local (real or restricted data, or secrets)"]
    return []


def check_content(path: str, text: str) -> list[str]:
    """Return violations found in a file's text."""
    path = path.replace("\\", "/")
    if path in CONTENT_EXEMPT:
        return []
    problems: list[str] = []
    if RESTRICTED_MARKER in text:
        problems.append(f"{path}: contains the restricted-content marker")
    for match in DFSA_DEEP_LINK.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        problems.append(
            f"{path}:{line}: deep link into dfsa.ae ({match.group(0)!r}); "
            "only the homepage https://www.dfsa.ae/ may be linked"
        )
    for label, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{path}:{line}: looks like a {label}")
    return problems


def _decode(data: bytes) -> str | None:
    if b"\0" in data[:8192]:
        return None  # binary file: path rules still apply, content is skipped
    return data.decode("utf-8", errors="replace")


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def _staged_files() -> list[tuple[str, bytes]]:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    files = []
    for raw in names:
        if raw:
            name = raw.decode("utf-8")
            files.append((name, _git("show", f":{name}")))
    return files


def _tracked_files(root: Path) -> list[tuple[str, bytes]]:
    names = _git("ls-files", "-z").split(b"\0")
    files = []
    for raw in names:
        if raw:
            name = raw.decode("utf-8")
            file_path = root / name
            files.append((name, file_path.read_bytes() if file_path.is_file() else b""))
    return files


def run(files: list[tuple[str, bytes]]) -> list[str]:
    problems: list[str] = []
    for name, data in files:
        problems.extend(check_path(name))
        text = _decode(data)
        if text is not None:
            problems.extend(check_content(name, text))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check files staged for commit")
    group.add_argument("--all", action="store_true", help="check every tracked file")
    parser.add_argument("paths", nargs="*", help="working-tree files to check")
    args = parser.parse_args(argv)

    root = Path(_git("rev-parse", "--show-toplevel").decode().strip()) if (args.staged or args.all) else Path.cwd()
    if args.all:
        files = _tracked_files(root)
    elif args.paths:
        files = [(p.replace("\\", "/"), Path(p).read_bytes()) for p in args.paths]
    else:
        files = _staged_files()

    problems = run(files)
    if problems:
        print("TESSERA commit guard: blocked.\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nKeep real data, DFSA facts and secrets local (see docs/data-governance.md).",
            file=sys.stderr,
        )
        return 1
    print(f"TESSERA commit guard: {len(files)} file(s) checked, no problems.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
