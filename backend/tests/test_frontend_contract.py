"""The frontend's reducer is written against these events, so a change here must reach it."""

import json
import re
from collections import Counter

from tessera.governance.language import lint_text
from tessera.governance.policies import load_language_policy

from .conftest import REPO_ROOT
from .frontend_contract import FIXTURE, record_worked_case

REDUCER = REPO_ROOT / "frontend" / "src" / "lib" / "reducer.ts"
BACKEND = REPO_ROOT / "backend" / "src" / "tessera"
#: Sent by the API itself when nothing is running a case. It is never stored.
API_ONLY = {"case.interrupted"}


def _recorded():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _emitted_types():
    pattern = re.compile(r"(?:_emit|record)\(\s*\"([a-z_]+\.[a-z_]+)\"")
    return {
        name
        for path in BACKEND.rglob("*.py")
        for name in pattern.findall(path.read_text(encoding="utf-8"))
    }


def test_the_frontend_fixture_is_what_the_crew_emits_today(populated_settings):
    fresh = record_worked_case(populated_settings)
    count = lambda events: Counter((event["type"], event["actor"]) for event in events)  # noqa: E731
    assert count(fresh["events"]) == count(_recorded()["events"])
    assert fresh["telemetry_requests"] == _recorded()["telemetry_requests"]


def test_every_event_the_reducer_handles_is_one_the_backend_sends():
    handled = set(re.findall(r'case "([a-z_]+\.[a-z_]+)":', REDUCER.read_text(encoding="utf-8")))
    assert len(handled) > 15
    assert not handled - _emitted_types() - API_ONLY


def test_the_fixture_holds_no_restricted_value():
    text = FIXTURE.read_text(encoding="utf-8")
    assert "Lumen Crest" not in text and "⟦R:" in text


def test_the_interface_uses_the_same_neutral_language_as_the_reports():
    policy = load_language_policy(REPO_ROOT / "policies")
    source = REPO_ROOT / "frontend" / "src"
    files = [
        path
        for path in source.rglob("*")
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    ]
    assert len(files) > 20
    found = {
        path.name: problems
        for path in files
        if (problems := lint_text(path.read_text(encoding="utf-8"), policy))
    }
    assert not found
