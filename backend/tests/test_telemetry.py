"""What a case's event log says about coordination."""

import asyncio
import json

from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.orchestration.graph import run_crew
from tessera.reporting.telemetry import case_telemetry, trace_bundle

from .conftest import REPO_ROOT
from .scripted import Routed, worked_example

OFFER = next(c for c in load_smoke_cases(REPO_ROOT) if c.id == "S09").offer().text


def worked_case(harness):
    script = Routed()
    setup = harness(OFFER, *[script] * 60, case_id="S09")
    script.queues = worked_example(setup)
    asyncio.run(run_crew(setup.env, today=FICTION_DATE))
    return setup


def test_telemetry_counts_what_coordination_did(harness):
    setup = worked_case(harness)
    telemetry = case_telemetry(setup.board, setup.store.read("S09"))
    assert telemetry["conflicts"]["by_type"] == {"C3": 2, "C5": 1}
    assert telemetry["conflicts"]["by_detector"] == {"detector": 3}
    assert telemetry["conflicts"]["unresolved"] == 0
    assert telemetry["challenges"] == {
        "sent": 1,
        "revisions": 1,
        "rebuttals": 0,
        "concessions": 0,
        "revision_rate": 1.0,
    }
    assert telemetry["verifier"]["vetoes"] == 1 and telemetry["verifier"]["approvals"] == 1
    assert telemetry["verifier"]["failed_gates"] == {"G5": 1}
    assert telemetry["conformity_flags"] == 0


def test_a_change_of_position_is_listed_for_the_evaluation_to_judge(harness):
    setup = worked_case(harness)
    revision = case_telemetry(setup.board, setup.store.read("S09"))["revisions"][0]
    assert revision["author"] == "JUR" and revision["type"] == "relevance"
    assert revision["before"]["status"] == "excluded"
    assert revision["after"]["status"] == "possible"


def test_spending_adds_up_by_phase(harness):
    setup = worked_case(harness)
    spending = case_telemetry(setup.board, setup.store.read("S09"))["spending"]
    assert sum(phase["requests"] for phase in spending.values()) == len(setup.transport.payloads)
    assert spending["R1"]["requests"] == 6  # a lookup turn and a final turn for each regulator
    assert spending["reconcile"]["requests"] == 1


def test_a_case_with_no_challenges_has_no_revision_rate(harness):
    setup = harness(OFFER)
    telemetry = case_telemetry(setup.board, setup.store.read("case-1"))
    assert telemetry["challenges"]["revision_rate"] is None
    assert telemetry["rounds"] == []


def test_a_trace_bundle_holds_the_whole_case_and_nothing_restricted(harness):
    setup = worked_case(harness)
    events = setup.store.read("S09")
    bundle = trace_bundle(setup.board, events)
    assert bundle["state"]["final"]["result"] == "CONFLICTS"
    assert len(bundle["events"]) == len(events)
    text = json.dumps(bundle, ensure_ascii=False)
    assert setup.gateway.leaked_values(text) == []
    assert "2026-01-14" not in text
