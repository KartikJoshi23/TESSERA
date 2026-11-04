"""The whole crew: the worked example, every smoke case, the limits, and properties of any run."""

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.reconciler import ReconcilerAgent
from tessera.agents.schemas import (
    EntailmentItem,
    ReconcilerRoundOutput,
    ReconcilerSynthesisOutput,
    RelevantRegulatorItem,
    ResolutionItem,
    SynthesisClaimItem,
    VerifierOutput,
)
from tessera.agents.verifier import VerifierAgent
from tessera.blackboard.board import Blackboard
from tessera.devdata import FICTION_DATE, load_smoke_cases, load_world
from tessera.governance.language import lint_text
from tessera.llm.runner import TurnResult
from tessera.llm.testing import chat_reply, json_reply
from tessera.llm.types import PermanentLLMError, TransientLLMError
from tessera.orchestration.conditions import CONDITIONS, CrewConfig, config_for
from tessera.orchestration.decision import PolicyDecision, derive_decision
from tessera.orchestration.graph import run_crew
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import AgentId, ResultCode

from .conftest import REPO_ROOT, CrewHarness
from .oracle import ORACLE, Oracle
from .scripted import REASONING, Routed, agent_of, case_data, jurisdiction_output, worked_example

CASES = {case.id: case for case in load_smoke_cases(REPO_ROOT)}
_DECISIVE = (
    "register_match",
    "licence_status",
    "licence_scope",
    "alert_hit",
    "contact_assessment",
    "payment_assessment",
    "register_no_match",
)
_P_RULES = {"C1": "P5", "C2": "P1", "C3": "P3", "C4": "P2", "C5": "P2", "C6": "P1", "C7": "P1"}


def text_of(key: str) -> str:
    return CASES[key].offer().text


def run(setup: CrewHarness, **kwargs: Any):
    return asyncio.run(run_crew(setup.env, today=FICTION_DATE, **kwargs))


# ------------------------------------------------------------------- a crew with no model


class Scripted(Agent):
    """A crew member whose turn is a Python function."""

    def __init__(self, agent_id: AgentId, turn: Any) -> None:
        self.agent_id = agent_id
        self.turn = turn
        self.tasks: list[Task] = []

    async def activate(self, env: AgentEnv, task: Task) -> TurnResult:
        self.tasks.append(task)
        output = self.turn(env, task)
        return TurnResult(agent_id=self.agent_id, output=output or {})


def decision_of(env: AgentEnv) -> PolicyDecision:
    return derive_decision(env, today=FICTION_DATE)


def synthesis_output(env: AgentEnv, **changes: Any) -> ReconcilerSynthesisOutput:
    decision = decision_of(env)
    findings = [f for f in env.board.live_findings() if f.assertion.type in _DECISIVE]
    values: dict[str, Any] = {
        "relevant_regulators": [
            RelevantRegulatorItem(regulator=regulator, status="primary")
            for regulator in sorted(env.board.relevant_regulators())
        ],
        "result": decision.result,
        "hard_conflicts": list(decision.hard_conflict_ids),
        "unverified_reasons": list(decision.unverified_reasons),
        "claims": [
            SynthesisClaimItem(finding_id=f.finding_id, text="A neutral sentence.")
            for f in findings
            if not f.unknown_evidence_ids
        ],
        "explanation": "The records were compared with the offer.",
    }
    return ReconcilerSynthesisOutput(**{**values, **changes})


def careful_reconciler(propose: Any = None) -> Scripted:
    """Settles conflicts by rule. ``propose`` can replace how it writes the proposal."""
    agent = ReconcilerAgent()

    def turn(env: AgentEnv, task: Task) -> None:
        if task.kind == "challenge_round":
            resolutions = [
                ResolutionItem(
                    conflict_id=conflict.conflict_id,
                    outcome="upheld",
                    precedence_rule=_P_RULES[conflict.type.value],
                )
                for conflict in env.board.open_conflicts()
            ]
            agent.apply(env, task, ReconcilerRoundOutput(resolutions=resolutions))
        elif task.kind == "synthesis":
            agent.apply(env, task, propose(env) if propose else synthesis_output(env))

    return Scripted(AgentId.REC, turn)


def approving_verifier() -> Scripted:
    agent = VerifierAgent()

    def turn(env: AgentEnv, task: Task) -> None:
        count = len(env.board.proposals[-1].claims)
        verdicts = [EntailmentItem(claim_index=i, verdict="supported") for i in range(count)]
        agent.apply(env, task, VerifierOutput(entailment=verdicts))

    return Scripted(AgentId.VER, turn)


def careful_crew(setup: CrewHarness, key: str, **replace: Agent) -> dict[AgentId, Agent]:
    oracle = Oracle(setup, ORACLE[key])

    def initial(step: Any) -> Any:
        return lambda env, task: step() if task.kind == "initial" else None

    crew: dict[AgentId, Agent] = {
        AgentId.JUR: Scripted(AgentId.JUR, initial(oracle.jurisdiction)),
        AgentId.CMA: Scripted(AgentId.CMA, initial(oracle.cma)),
        AgentId.DFSA: Scripted(AgentId.DFSA, initial(oracle.dfsa)),
        AgentId.VARA: Scripted(AgentId.VARA, initial(oracle.vara)),
        AgentId.CLN: Scripted(AgentId.CLN, initial(oracle.clone_check)),
        AgentId.REC: careful_reconciler(),
        AgentId.VER: approving_verifier(),
    }
    crew.update({AgentId[name]: agent for name, agent in replace.items()})
    return crew


def careful_case(harness, key: str, condition=None, **replace: Agent):
    setup = harness(text_of(key), case_id=key)
    config = config_for(condition) if condition else None
    return setup, run(setup, crew=careful_crew(setup, key, **replace), config=config)


@pytest.mark.parametrize("key", sorted(ORACLE))
def test_a_careful_crew_finishes_every_case_with_its_gold_result(harness, key):
    setup, final = careful_case(harness, key)
    assert final.result is CASES[key].gold_label, setup.board.verifier_reports
    assert set((*final.hard_conflicts, *final.unverified_reasons)) == set(CASES[key].gold_reasons)
    assert setup.board.verifier_reports[-1].decision == "APPROVE"
    assert setup.board.open_conflicts() == []


# ------------------------------------------------------------------- the worked example (§6.10)


def worked_case(harness, adjust=None):
    script = Routed()
    setup = harness(text_of("S09"), *[script] * 60, case_id="S09")
    script.queues = worked_example(setup)
    if adjust:
        adjust(setup, script.queues)
    return setup, run(setup)


def requests_by(setup: CrewHarness, agent: str) -> str:
    wanted = [p for p in setup.transport.payloads if agent_of(p) == agent]
    return json.dumps(wanted, ensure_ascii=False)


def stored_text(setup: CrewHarness) -> str:
    return json.dumps([e.payload for e in setup.store.read("S09")], ensure_ascii=False, default=str)


def test_the_worked_example_gives_the_expected_trace(harness):
    setup, final = worked_case(harness)
    board = setup.board
    phases = [e.payload["phase"] for e in setup.store.read("S09") if e.type == "round.started"]
    assert phases == [
        "R0",
        "R1",
        "R2",
        "reconcile",
        "synthesis",
        "verify",
        "remediate",
        "verify",
    ]
    sent = [(m.sender.value, m.performative.value) for m in board.messages]
    for step in (
        ("DFSA", "REQUEST"),
        ("VARA", "CHALLENGE"),
        ("JUR", "REVISE"),
        ("REC", "RESOLVE"),
        ("VER", "VETO"),
        ("VER", "APPROVE"),
    ):
        assert step in sent, step
    assert board.inbox(AgentId.JUR) == [] and board.inbox(AgentId.CLN) == []
    # Jurisdiction's exclusion of VARA changed, with a citation, before conflicts were detected.
    vara = next(
        f
        for f in board.live_findings("relevance")
        if f.author is AgentId.JUR and f.assertion.regulator == "VARA"
    )
    assert vara.version == 2 and vara.assertion.status == "possible"
    assert sorted(c.type.value for c in board.conflicts.values()) == ["C3", "C3", "C5"]
    assert {r.precedence_rule for r in board.resolutions.values()} == {"P2", "P3"}
    # The Verifier refused the wording, and the second proposal passed.
    first, second = board.verifier_reports
    assert first.decision == "VETO" and [g.gate for g in first.gates if not g.passed] == ["G5"]
    assert second.decision == "APPROVE" and second.proposal_version == 2
    assert final.result is ResultCode.CONFLICTS
    assert set(final.hard_conflicts) == {"HC1", "HC4", "HC5"}
    assert "clone" not in final.explanation
    assert not any(f.unknown_evidence_ids for f in board.findings.values())
    assert board.failures == [] and board.rejections == []


def test_a_veto_on_wording_needs_no_new_lookups(harness):
    setup, _ = worked_case(harness)
    round_turns = [p for p in setup.transport.payloads if "Deal with every open" in str(p)]
    assert len(round_turns) == 1


def test_no_restricted_value_or_gold_label_leaves_or_is_stored(harness):
    setup, _ = worked_case(harness)
    setup.assert_no_leaks()
    assert "gold_" not in setup.outgoing_text()
    assert setup.gateway.leaked_values(stored_text(setup)) == []


def recorded_dfsa_details() -> list[str]:
    """Recorded DFSA facts that are not identifiers, so the gateway does not mask them."""
    world = load_world(REPO_ROOT)
    register, alerts = world["dfsa_register"], world["dfsa_alerts"]
    services = [item for row in register for item in row["permitted_services"].split(";")]
    streets = [row["address"].split(",")[0] for row in register]
    return [*services, *streets, *(row["alert_date"] for row in alerts)]


def test_recorded_dfsa_details_never_leave_the_machine_or_reach_the_log(harness):
    """§9.2: a model gets placeholders and tool-computed relations, never recorded wording."""
    setup, _ = worked_case(harness)
    outgoing, stored = setup.outgoing_text(), stored_text(setup)
    for detail in recorded_dfsa_details():
        assert detail not in outgoing, detail
        assert detail not in stored, detail
    for field in ("permitted_services", "alert_date"):
        assert field not in outgoing, field


def test_models_get_the_relations_the_tools_worked_out(harness):
    setup, _ = worked_case(harness)
    view = next(case_data(p) for p in setup.transport.payloads if agent_of(p) == "VER")
    facts = [e["facts"] for e in view["evidence"] if e.get("facts")]
    register = next(f for f in facts if "covers_activities" in f)
    alert = next(f for f in facts if "category" in f)
    assert "SEC.ADVICE" in register["covers_activities"]
    assert "VA.EXCHANGE" not in register["covers_activities"]
    assert register["scope_complete"] is True and register["zone"] == "DIFC"
    assert alert["category"] == "impersonated_authorised_firm"


def test_a_zone_stays_visible_when_its_address_is_masked(harness):
    setup, _ = worked_case(harness)
    assert "⟦R:ADDRESS-" in setup.board.case.offer_text
    assert ", DIFC, Dubai" in setup.board.case.offer_text
    assert "Gate Village" not in setup.board.case.offer_text
    assert setup.gateway.unmask(setup.board.case.offer_text) == text_of("S09")


def test_restricted_evidence_holds_row_references_only(harness):
    setup, _ = worked_case(harness)
    restricted = [e for e in setup.board.evidence.values() if e.restricted]
    assert restricted and all(e.restricted_ref for e in restricted)


def test_the_verifier_never_reads_agents_reasoning(harness):
    setup, _ = worked_case(harness)
    assert REASONING in requests_by(setup, "REC")
    assert REASONING not in requests_by(setup, "VER")


def test_the_verifier_reads_all_evidence_not_only_what_claims_cite(harness):
    setup, _ = worked_case(harness)
    view = next(case_data(p) for p in setup.transport.payloads if agent_of(p) == "VER")
    cited = {e for claim in view["claims"] for e in claim["evidence_ids"]}
    shown = {e["evidence_id"] for e in view["evidence"]}
    assert shown == set(setup.board.evidence) and cited < shown


def test_replaying_a_whole_case_rebuilds_it(harness):
    setup, _ = worked_case(harness)
    replayed = Blackboard.replay(setup.store, "S09", gateway=setup.gateway)
    assert replayed.snapshot() == setup.board.snapshot()


def test_a_failed_agent_is_recorded_and_the_case_carries_on(harness):
    def drop_cma(setup, queues):
        queues["CMA"] = [PermanentLLMError("HTTP 400: bad request")]

    setup, final = worked_case(harness, drop_cma)
    assert setup.board.failures[0]["code"] == "model_error"
    assert "model_error" in requests_by(setup, "REC")
    assert any(e.type == "agent.failed" for e in setup.store.read("S09"))
    assert final.result is ResultCode.CONFLICTS  # the evidence-backed conflicts still stand


def test_a_case_with_no_proposal_ends_as_could_not_verify(harness):
    def no_proposal(setup, queues):
        queues["REC"] = [queues["REC"][0], chat_reply("no"), chat_reply("still no")]
        queues["VER"] = []

    setup, final = worked_case(harness, no_proposal)
    assert setup.board.proposals == [] and setup.board.verifier_reports == []
    assert final.result is ResultCode.UNVERIFIED and "U7" in final.unverified_reasons
    assert final.explanation and not lint_text(final.explanation, setup.env.language)


# ------------------------------------------------------------------- the veto


def test_an_unsupported_claim_is_vetoed_and_can_be_fixed(harness):
    calls = {"count": 0}
    agent = VerifierAgent()

    def strict_once(env: AgentEnv, task: Task) -> None:
        calls["count"] += 1
        claims = len(env.board.proposals[-1].claims)
        verdict = "unsupported" if calls["count"] == 1 else "supported"
        verdicts = [EntailmentItem(claim_index=i, verdict=verdict) for i in range(claims)]
        agent.apply(env, task, VerifierOutput(entailment=verdicts))

    setup, final = careful_case(harness, "S10", VER=Scripted(AgentId.VER, strict_once))
    assert [r.decision for r in setup.board.verifier_reports] == ["VETO", "APPROVE"]
    assert final.result is ResultCode.CONFLICTS
    assert final.proposal_version == 2


def test_a_veto_that_stands_ends_as_could_not_verify(harness):
    agent = VerifierAgent()

    def always_refuses(env: AgentEnv, task: Task) -> None:
        claims = len(env.board.proposals[-1].claims)
        verdicts = [EntailmentItem(claim_index=i, verdict="unsupported") for i in range(claims)]
        agent.apply(env, task, VerifierOutput(entailment=verdicts))

    setup, final = careful_case(harness, "S10", VER=Scripted(AgentId.VER, always_refuses))
    assert [r.decision for r in setup.board.verifier_reports] == ["VETO", "VETO"]
    assert final.result is ResultCode.UNVERIFIED and "U6" in final.unverified_reasons
    assert final.claims == ()


def test_there_is_only_one_remediation(harness):
    reconciler = careful_reconciler()
    agent = VerifierAgent()

    def always_refuses(env: AgentEnv, task: Task) -> None:
        claims = len(env.board.proposals[-1].claims)
        verdicts = [EntailmentItem(claim_index=i, verdict="unsupported") for i in range(claims)]
        agent.apply(env, task, VerifierOutput(entailment=verdicts))

    setup, _ = careful_case(
        harness, "S10", REC=reconciler, VER=Scripted(AgentId.VER, always_refuses)
    )
    assert len(setup.board.proposals) == 2
    assert [t.kind for t in reconciler.tasks].count("remediate") == 1


def test_a_failed_verifier_blocks_the_result(harness):
    def fails(env: AgentEnv, task: Task) -> Any:
        return None

    class Failing(Scripted):
        async def activate(self, env: AgentEnv, task: Task) -> TurnResult:
            return TurnResult(agent_id=AgentId.VER, failure="model_error")

    setup, final = careful_case(harness, "S10", VER=Failing(AgentId.VER, fails))
    assert final.result is ResultCode.UNVERIFIED
    assert "could not finish" in setup.board.verifier_reports[-1].veto_reasons[0]


def test_an_overconfident_proposal_cannot_become_consistent(harness):
    agent = ReconcilerAgent()

    def overconfident(env: AgentEnv, task: Task) -> None:
        if task.kind == "synthesis":
            output = synthesis_output(
                env, result=ResultCode.CONSISTENT, hard_conflicts=[], unverified_reasons=[]
            )
            agent.apply(env, task, output)

    setup, final = careful_case(harness, "S23", REC=Scripted(AgentId.REC, overconfident))
    failed = {g.gate for g in setup.board.verifier_reports[0].gates if not g.passed}
    assert {"G3", "G8"} <= failed
    assert final.result is ResultCode.UNVERIFIED


def test_a_veto_with_grounds_gives_the_reconciler_a_chance_to_ask(harness):
    written = {"count": 0}

    def wrong_once(env: AgentEnv) -> ReconcilerSynthesisOutput:
        written["count"] += 1
        return synthesis_output(
            env, **({"hard_conflicts": ["HC1"]} if written["count"] == 1 else {})
        )

    reconciler = careful_reconciler(wrong_once)
    setup, final = careful_case(harness, "S10", REC=reconciler)
    failed = {g.gate for g in setup.board.verifier_reports[0].gates if not g.passed}
    assert failed == {"G4"}
    assert [t.kind for t in reconciler.tasks][-2:] == ["remediate", "synthesis"]
    assert reconciler.tasks[-1].revision is True
    assert final.result is ResultCode.CONFLICTS


def test_a_report_states_only_the_hard_conflicts_the_evidence_backs(harness):
    def padded(env: AgentEnv) -> ReconcilerSynthesisOutput:
        return synthesis_output(env, hard_conflicts=["HC2", "HC4"])

    _, final = careful_case(harness, "S10", REC=careful_reconciler(padded))
    assert final.hard_conflicts == ("HC4",)


def test_a_report_states_every_hard_conflict_the_evidence_backs(harness):
    """A proposal needs only one to pass the gates, and can miss the others."""

    def partial(env: AgentEnv) -> ReconcilerSynthesisOutput:
        return synthesis_output(env, hard_conflicts=["HC2"])

    _, final = careful_case(harness, "S12", REC=careful_reconciler(partial))
    assert set(final.hard_conflicts) == {"HC1", "HC2"}


def test_a_more_cautious_proposal_is_kept_and_counted_as_an_under_call(harness):
    def cautious(env: AgentEnv) -> ReconcilerSynthesisOutput:
        return synthesis_output(
            env, result=ResultCode.UNVERIFIED, hard_conflicts=[], unverified_reasons=["U3"]
        )

    setup, final = careful_case(harness, "S10", REC=careful_reconciler(cautious))
    assert final.result is ResultCode.UNVERIFIED
    assert final.detail["under_call"] is True and final.detail["policy_result"] == "CONFLICTS"
    assert setup.board.verifier_reports[-1].decision == "APPROVE"


# ------------------------------------------------------------------- limits


def test_challenge_rounds_stop_at_the_limit(harness):
    reconciler = careful_reconciler()
    agent = ReconcilerAgent()

    def never_settles(env: AgentEnv, task: Task) -> None:
        if task.kind == "challenge_round":
            target = env.board.live_findings("licence_scope")[0]
            challenge = {
                "performative": "CHALLENGE",
                "to": target.author,
                "target_finding_id": target.finding_id,
                "question": "Are you sure?",
                "rule_ids": ["SCOPE-CMA-01"],
            }
            agent.apply(env, task, ReconcilerRoundOutput(challenges=[challenge]))
        elif task.kind == "synthesis":
            agent.apply(env, task, synthesis_output(env))

    reconciler.turn = never_settles
    setup, final = careful_case(harness, "S10", REC=reconciler)
    assert [t.kind for t in reconciler.tasks].count("challenge_round") == 3
    assert "U5" in (*final.unverified_reasons, *setup.board.proposals[-1].unverified_reasons)


def test_a_round_that_changes_nothing_ends_the_rounds(harness):
    reconciler = careful_reconciler()
    agent = ReconcilerAgent()

    def idle(env: AgentEnv, task: Task) -> None:
        if task.kind == "synthesis":
            agent.apply(env, task, synthesis_output(env))

    reconciler.turn = idle
    careful_case(harness, "S10", REC=reconciler)
    assert [t.kind for t in reconciler.tasks].count("challenge_round") == 1


def test_a_clean_case_needs_no_challenge_round(harness):
    reconciler = careful_reconciler()
    careful_case(harness, "S01", REC=reconciler)
    assert [t.kind for t in reconciler.tasks] == ["synthesis"]


def test_the_request_budget_ends_a_case_cleanly(harness):
    def cap(setup, queues):
        setup.env.runner.meter.max_requests = 3

    setup, final = worked_case(harness, cap)
    assert final.result is ResultCode.UNVERIFIED and "U7" in final.unverified_reasons
    assert setup.env.runner.meter.requests == 3


def test_a_provider_outage_ends_a_case_cleanly(harness):
    setup = harness(text_of("S09"), *[TransientLLMError("HTTP 503")] * 30)
    final = run(setup)
    assert final.result is ResultCode.UNVERIFIED and "U7" in final.unverified_reasons
    assert len({f["agent"] for f in setup.board.failures}) >= 6


# ------------------------------------------------------------------- ablation switches


def test_every_crew_condition_has_a_configuration():
    assert set(CONDITIONS) == {
        SystemCondition.CREW_FULL,
        SystemCondition.CREW_SHARE,
        SystemCondition.CREW_SILO,
        SystemCondition.CREW_NV,
    }
    assert config_for(SystemCondition.CREW_NV) == CrewConfig(verifier=False)


def test_conditions_differ_only_in_their_switches():
    full = config_for(SystemCondition.CREW_FULL)
    assert full.max_challenge_rounds == 3 and full.max_remediations == 1
    for condition in CONDITIONS:
        config = config_for(condition)
        assert config.max_challenge_rounds == full.max_challenge_rounds
        assert config.max_remediations == full.max_remediations


@pytest.mark.parametrize(
    ("condition", "share", "messages"),
    [
        (SystemCondition.CREW_SHARE, True, False),
        (SystemCondition.CREW_SILO, False, False),
    ],
)
def test_conditions_without_challenges_skip_the_rounds(harness, condition, share, messages):
    reconciler = careful_reconciler()
    jurisdiction = Scripted(AgentId.JUR, lambda env, task: None)
    setup = harness(text_of("S10"), case_id="S10")
    crew = careful_crew(setup, "S10", REC=reconciler)
    oracle_turn = crew[AgentId.JUR].turn
    jurisdiction.turn = oracle_turn
    crew[AgentId.JUR] = jurisdiction
    run(setup, crew=crew, config=config_for(condition))
    assert "challenge_round" not in [t.kind for t in reconciler.tasks]
    assert jurisdiction.tasks[0].options.share is share
    assert jurisdiction.tasks[0].options.messages is messages


def plain_crew(harness, condition: SystemCondition) -> tuple[CrewHarness, list[bool]]:
    """Real agents and minimal replies. VARA challenges Jurisdiction if it can see a finding."""
    script = Routed()
    setup = harness(text_of("S09"), *[script] * 40, case_id="S09")
    saw_findings: list[bool] = []
    relevant = [{"regulator": r, "status": "possible"} for r in ("CMA", "DFSA", "VARA")]

    def vara(payload: dict[str, Any]) -> dict[str, Any]:
        findings = case_data(payload).get("jurisdiction_findings", [])
        saw_findings.append(bool(findings))
        outgoing = [
            {
                "performative": "CHALLENGE",
                "to": "JUR",
                "target_finding_id": finding["finding_id"],
                "question": "Is this right?",
                "rule_ids": ["JUR-01"],
            }
            for finding in findings[:1]
        ]
        return json_reply({"relevance": {"status": "possible"}, "outgoing": outgoing})

    def clone(payload: dict[str, Any]) -> dict[str, Any]:
        contacts = [
            {"cp_id": c["cp_id"], "status": "not_comparable"}
            for c in case_data(payload)["contact_points"]
            if c["role"] == "deciding"
        ]
        return json_reply({"contacts": contacts})

    regulator = json_reply({"relevance": {"status": "possible"}})
    script.queues = {
        "JUR": [json_reply(jurisdiction_output())],
        "CMA": [regulator],
        "DFSA": [regulator],
        "VARA": [vara],
        "CLN": [clone],
        "REC": [
            json_reply(
                {
                    "relevant_regulators": relevant,
                    "result": "UNVERIFIED",
                    "unverified_reasons": ["U1"],
                    "explanation": "The records were compared.",
                }
            )
        ],
        "VER": [json_reply({"entailment": []})],
    }
    run(setup, config=config_for(condition))
    return setup, saw_findings


def test_without_messages_an_agents_challenge_is_dropped(harness):
    setup, saw_findings = plain_crew(harness, SystemCondition.CREW_SHARE)
    assert saw_findings == [True]  # it could see a finding, and tried to challenge it
    assert "CHALLENGE" not in {m.performative.value for m in setup.board.messages}
    assert setup.board.rejections == []


def test_without_sharing_agents_work_alone(harness):
    setup, saw_findings = plain_crew(harness, SystemCondition.CREW_SILO)
    assert saw_findings == [False]
    clone = next(p for p in setup.transport.payloads if agent_of(p) == "CLN")
    assert "regulator_findings" not in case_data(clone)
    # The Reconciler and the Verifier still see everything, in every condition.
    reconciler = next(p for p in setup.transport.payloads if agent_of(p) == "REC")
    assert case_data(reconciler)["findings"]


def test_without_the_verifier_a_proposal_stands_unchecked(harness):
    agent = ReconcilerAgent()

    def overconfident(env: AgentEnv, task: Task) -> None:
        if task.kind == "synthesis":
            output = synthesis_output(
                env, result=ResultCode.CONSISTENT, hard_conflicts=[], unverified_reasons=[]
            )
            agent.apply(env, task, output)

    setup, final = careful_case(
        harness, "S23", SystemCondition.CREW_NV, REC=Scripted(AgentId.REC, overconfident)
    )
    assert final.result is ResultCode.CONSISTENT
    assert setup.board.verifier_reports == []
    assert final.detail["policy_result"] == "UNVERIFIED"  # the cost of the ablation stays visible


def test_the_linter_still_runs_without_the_verifier(harness):
    agent = ReconcilerAgent()

    def careless(env: AgentEnv, task: Task) -> None:
        if task.kind == "synthesis":
            agent.apply(env, task, synthesis_output(env, explanation="This firm is a scam."))

    setup, final = careful_case(
        harness, "S23", SystemCondition.CREW_NV, REC=Scripted(AgentId.REC, careless)
    )
    assert "scam" not in final.explanation
    assert not lint_text(final.explanation, setup.env.language)
    assert any(e.type == "report.wording_replaced" for e in setup.store.read("S23"))


def test_a_withheld_explanation_never_contradicts_its_result(harness):
    def careless(env: AgentEnv) -> ReconcilerSynthesisOutput:
        return synthesis_output(env, explanation="This firm is a scam.")

    _, final = careful_case(
        harness, "S10", SystemCondition.CREW_NV, REC=careful_reconciler(careless)
    )
    assert final.result is ResultCode.CONFLICTS
    assert "could not be confirmed" not in final.explanation


# ------------------------------------------------------------------- properties of any run


@dataclass
class Unreliable:
    """A model that does whatever a seeded random generator says."""

    rng: random.Random
    setup: CrewHarness | None = None

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = agent_of(payload)
        roll = self.rng.random()
        if roll < 0.1:
            raise TransientLLMError("HTTP 503")
        if roll < 0.2:
            return chat_reply("not json at all")
        if roll < 0.3:
            return json_reply({"unexpected": True})
        return json_reply(self.reply(agent, payload))

    def reply(self, agent: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.setup is not None
        board = self.setup.board
        findings = list(board.findings)
        rng = self.rng
        if agent == "JUR":
            return jurisdiction_output()
        if agent in ("CMA", "DFSA", "VARA"):
            return {
                "relevance": {"status": rng.choice(["primary", "possible", "excluded"])},
                "no_match_evidence_ids": rng.choice([[], ["E-feedfacefeedface"]]),
            }
        if agent == "CLN":
            status = rng.choice(["matches_official", "alert_listed", "not_on_record"])
            points = board.case.contact_points
            return {"contacts": [{"cp_id": p.cp_id, "status": status} for p in points]}
        if agent == "VER":
            verdict = rng.choice(["supported", "unsupported"])
            return {
                "entailment": [
                    {"claim_index": i, "verdict": verdict}
                    for i in range(len(board.proposals[-1].claims))
                ]
            }
        conflicts = [c.conflict_id for c in board.open_conflicts()]
        picked = rng.sample(findings, k=min(3, len(findings)))
        return {
            "resolutions": [
                {
                    "conflict_id": conflict,
                    "outcome": rng.choice(["upheld", "unresolved"]),
                    "precedence_rule": rng.choice(["P1", "P7"]),
                }
                for conflict in conflicts
            ],
            "result": rng.choice(["CONSISTENT", "CONFLICTS", "UNVERIFIED"]),
            "hard_conflicts": ["HC1"],
            "unverified_reasons": ["U1"],
            "claims": [{"finding_id": f, "text": "A sentence."} for f in picked],
            "explanation": rng.choice(["The records were compared.", "This is a scam."]),
        }


@pytest.fixture(scope="module")
def shared_world(tmp_path_factory):
    from .conftest import populate

    return populate(tmp_path_factory.mktemp("world") / "data")


@given(
    seed=st.integers(0, 2**32 - 1),
    key=st.sampled_from(sorted(CASES)),
    condition=st.sampled_from(sorted(CONDITIONS, key=str)),
)
@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_any_behaviour_ends_in_a_safe_result(shared_world, seed, key, condition):
    model = Unreliable(random.Random(seed))
    setup = CrewHarness(shared_world, text_of(key), *[model] * 400, case_id=key)
    model.setup = setup
    final = run(setup, config=config_for(condition))
    board = setup.board

    # Every case finishes, within its budget.
    assert board.final is not None
    assert setup.env.runner.meter.requests <= setup.env.runner.meter.max_requests

    verified = config_for(condition).verifier
    decision = decision_of(setup.env)
    if verified:
        # A result is never more reassuring than the evidence supports.
        if final.result is ResultCode.CONSISTENT:
            assert decision.result is ResultCode.CONSISTENT
        # A veto that stands never leaves a result in place.
        if board.verifier_reports and board.verifier_reports[-1].decision == "VETO":
            assert final.result is ResultCode.UNVERIFIED
            assert "U6" in final.unverified_reasons
    # Every "Could not verify" says why.
    if final.result is ResultCode.UNVERIFIED:
        assert final.unverified_reasons

    # Whatever a model wrote, the result is worded within policy.
    assert not lint_text(final.explanation, setup.env.language)
    assert not any(lint_text(claim.text, setup.env.language) for claim in final.claims)

    # Nothing restricted left the machine, and the case can be rebuilt from its log.
    setup.assert_no_leaks()
    assert Blackboard.replay(setup.store, key, gateway=setup.gateway).snapshot() == board.snapshot()


def flaky_crew(setup: CrewHarness, key: str, rng: random.Random) -> dict[AgentId, Agent]:
    """The careful crew with faults: real evidence, but turns get skipped and proposals overreach.

    A model that invents everything never earns an approval. This crew often does, so the
    properties below are tested on results that really could be wrong.
    """

    def propose(env: AgentEnv) -> ReconcilerSynthesisOutput:
        honest = synthesis_output(env)
        roll = rng.random()
        if roll < 0.35:
            return honest
        if roll < 0.6:
            return synthesis_output(
                env, result=ResultCode.CONSISTENT, hard_conflicts=[], unverified_reasons=[]
            )
        if roll < 0.8:
            return synthesis_output(env, result=ResultCode.CONFLICTS, hard_conflicts=["HC1"])
        return synthesis_output(env, explanation="This firm is a scam.")

    verifier = VerifierAgent()

    def verify(env: AgentEnv, task: Task) -> None:
        verdict = "unsupported" if rng.random() < 0.15 else "supported"
        verdicts = [
            EntailmentItem(claim_index=i, verdict=verdict)
            for i in range(len(env.board.proposals[-1].claims))
        ]
        verifier.apply(env, task, VerifierOutput(entailment=verdicts))

    crew = careful_crew(
        setup, key, REC=careful_reconciler(propose), VER=Scripted(AgentId.VER, verify)
    )
    for agent_id in (AgentId.JUR, AgentId.CMA, AgentId.DFSA, AgentId.VARA, AgentId.CLN):
        member = crew[agent_id]
        assert isinstance(member, Scripted)
        careful = member.turn

        def maybe(env: AgentEnv, task: Task, careful: Any = careful) -> Any:
            return None if rng.random() < 0.12 else careful(env, task)

        member.turn = maybe
    return crew


@given(
    seed=st.integers(0, 2**32 - 1),
    key=st.sampled_from(sorted(CASES)),
)
@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_a_result_is_never_more_reassuring_than_the_evidence(shared_world, seed, key):
    setup = CrewHarness(shared_world, text_of(key), case_id=key)
    final = run(setup, crew=flaky_crew(setup, key, random.Random(seed)))
    board = setup.board
    decision = decision_of(setup.env)
    last = board.verifier_reports[-1] if board.verifier_reports else None

    if final.result is ResultCode.CONSISTENT:
        assert last is not None and last.decision == "APPROVE"
        assert decision.result is ResultCode.CONSISTENT and all(decision.conditions.values())
    if final.result is ResultCode.CONFLICTS:
        assert last is not None and last.decision == "APPROVE"
        assert set(final.hard_conflicts) & set(decision.hard_conflict_ids)
    if last is not None and last.decision == "VETO":
        assert final.result is ResultCode.UNVERIFIED and "U6" in final.unverified_reasons
    if final.result is ResultCode.UNVERIFIED:
        assert final.unverified_reasons
    assert not lint_text(final.explanation, setup.env.language)
