"""Tests for the commit guard (scripts/check_restricted.py). This file is exempt from the guard's
content checks, because it must contain the patterns the guard looks for."""

import importlib.util
import socket

import pytest

from .conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "check_restricted", REPO_ROOT / "scripts" / "check_restricted.py"
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.mark.parametrize(
    "path",
    [
        "PS.md",
        ".env",
        ".env.local",
        "data/restricted/dfsa/register_facts.csv",
        "data/handrecords/vara_register.csv",
        "data/inbox/cma_licensed/export.xlsx",
        "data/snapshots/cma_licensed/x/records.jsonl",
        "datasets/message_level/test/items.jsonl",
        "runs/run-1/events.db",
    ],
)
def test_local_only_paths_are_blocked(path):
    assert guard.check_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "data/README.md",
        "data/handrecords/README.md",
        "data/handrecords/templates/vara_register.csv",
        "datasets/README.md",
        "backend/src/tessera/__init__.py",
        "implementation-plan.md",
    ],
)
def test_code_docs_and_templates_are_allowed(path):
    assert guard.check_path(path) == []


def test_dfsa_deep_links_are_blocked_but_the_homepage_is_fine():
    assert guard.check_content("a.md", "see https://www.dfsa.ae/alerts/some-alert")
    assert guard.check_content("a.md", "dfsa.ae/public-register/firms")
    assert guard.check_content("a.md", "see https://www.dfsa.ae/ for details") == []
    assert guard.check_content("a.md", "<https://www.dfsa.ae/> and `dfsa.ae/<path>`") == []


def test_api_keys_and_the_restricted_marker_are_blocked():
    assert guard.check_content("a.py", "key = 'nvapi-" + "A1b2" * 10 + "'")
    assert guard.check_content("a.py", "token = 'ghp_" + "x" * 36 + "'")
    assert guard.check_content("a.txt", "TESSERA-RESTRICTED")
    assert guard.check_content("a.py", "NVIDIA_API_KEY=") == []


def test_the_guard_itself_is_exempt_from_content_checks():
    source = (REPO_ROOT / "scripts" / "check_restricted.py").read_text(encoding="utf-8")
    assert guard.check_content("scripts/check_restricted.py", source) == []


def test_run_combines_path_and_content_checks():
    problems = guard.run([("PS.md", b"notes"), ("notes.md", b"https://www.dfsa.ae/alerts/x")])
    assert len(problems) == 2


def test_tests_cannot_reach_the_network():
    with pytest.raises(RuntimeError, match="network access attempted"):
        socket.getaddrinfo("example.com", 80)
