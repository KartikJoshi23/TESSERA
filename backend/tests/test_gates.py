"""The Verifier's deterministic gates, G1–G8."""

from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.governance.links import DFSA_HOMEPAGE
from tessera.orchestration.decision import derive_decision
from tessera.orchestration.gates import clean_links, is_under_call, run_gates
from tessera.protocol.claims import CoverageGap
from tessera.protocol.common import AgentId, ResultCode
from tessera.protocol.messages import MessageDraft, Performative
from tessera.protocol.results import ProposedResult, RegulatorCoverage, ResultClaim

from .conftest import REPO_ROOT
from .oracle import run_oracle

CASES = {case.id: case for case in load_smoke_cases(REPO_ROOT)}


def oracle_case(harness, key):
    setup = harness(CASES[key].offer().text, case_id=key)
    run_oracle(setup, key)
    return setup


def claim_on(finding, text="A neutral sentence."):
    return ResultClaim(
        finding_id=finding.finding_id,
        assertion=finding.assertion,
        text=text,
        evidence_ids=finding.evidence_ids,
    )


def proposal(setup, result, *claims, hard=(), reasons=(), explanation="A neutral explanation."):
    relevant = sorted({"CMA", "DFSA", "VARA"} & _relevant(setup))
    return ProposedResult(
        version=1,
        author=AgentId.REC,
        result=result,
        hard_conflicts=hard,
        unverified_reasons=reasons,
        claims=claims,
        regulators=tuple(
            RegulatorCoverage(regulator=r, relevance="primary", checked=True) for r in relevant
        ),
        explanation=explanation,
    )


def _relevant(setup):
    return {
        f.assertion.regulator
        for f in setup.board.live_findings("relevance")
        if f.assertion.status in ("primary", "possible")
    }


def gates_for(setup, proposed):
    decision = derive_decision(setup.env, today=FICTION_DATE)
    return {gate.gate: gate for gate in run_gates(setup.env, proposed, decision)}


def test_a_sound_proposal_passes_every_gate(harness):
    setup = oracle_case(harness, "S15")
    contact = setup.board.live_findings("contact_assessment")[0]
    gates = gates_for(
        setup, proposal(setup, ResultCode.CONFLICTS, claim_on(contact), hard=("HC5",))
    )
    assert [g for g in gates.values() if not g.passed] == []
    assert list(gates) == [f"G{i}" for i in range(1, 9)]


def test_g1_every_claim_needs_evidence_from_this_case(harness):
    setup = oracle_case(harness, "S15")
    contact = setup.board.live_findings("contact_assessment")[0]
    bare = claim_on(contact).model_copy(update={"evidence_ids": ()})
    invented = claim_on(contact).model_copy(update={"evidence_ids": ("E-feedfacefeedface",)})
    assert not gates_for(setup, proposal(setup, ResultCode.CONFLICTS, bare))["G1"].passed
    assert not gates_for(setup, proposal(setup, ResultCode.CONFLICTS, invented))["G1"].passed


def test_g1_lets_a_gap_stand_without_evidence(harness):
    setup = oracle_case(harness, "S21")
    gap = setup.board.post_finding(
        AgentId.ORC, CoverageGap(regulator="CBUAE", reason="not covered")
    )
    gates = gates_for(setup, proposal(setup, ResultCode.UNVERIFIED, claim_on(gap), reasons=("U2",)))
    assert gates["G1"].passed


def test_g2_a_claim_must_match_its_finding(harness):
    setup = oracle_case(harness, "S23")
    contact = setup.board.live_findings("contact_assessment")[0]
    altered = claim_on(contact).model_copy(
        update={"assertion": contact.assertion.model_copy(update={"status": "matches_official"})}
    )
    gate = gates_for(setup, proposal(setup, ResultCode.CONSISTENT, altered))["G2"]
    assert not gate.passed and "differs from its finding" in gate.detail


def test_g2_a_claim_needs_a_finding_that_still_stands(harness):
    setup = oracle_case(harness, "S23")
    contact = setup.board.live_findings("contact_assessment")[0]
    challenge = setup.board.send(
        MessageDraft(
            sender=AgentId.REC,
            recipients=(AgentId.CLN,),
            performative=Performative.CHALLENGE,
            refs=(contact.finding_id,),
            rule_ids=("CLONE-01",),
            body={"question": "Why?"},
        )
    )
    setup.board.send(
        MessageDraft(
            sender=AgentId.CLN,
            recipients=(AgentId.REC,),
            performative=Performative.CONCEDE,
            refs=(contact.finding_id,),
            in_reply_to=challenge.msg_id,
        )
    )
    gate = gates_for(setup, proposal(setup, ResultCode.UNVERIFIED, claim_on(contact)))["G2"]
    assert not gate.passed and "no longer stands" in gate.detail


def test_g2_a_claim_must_agree_with_the_tools(harness):
    setup = oracle_case(harness, "S23")
    contact = setup.board.live_findings("contact_assessment")[0]
    lied = contact.model_copy(
        update={"assertion": contact.assertion.model_copy(update={"status": "matches_official"})}
    )
    setup.board.findings[contact.finding_id] = lied
    gate = gates_for(setup, proposal(setup, ResultCode.CONSISTENT, claim_on(lied)))["G2"]
    assert not gate.passed and "no comparison shows" in gate.detail


def test_g3_consistent_needs_every_condition(harness):
    setup = oracle_case(harness, "S23")
    gate = gates_for(setup, proposal(setup, ResultCode.CONSISTENT))["G3"]
    assert not gate.passed and "K4" in gate.detail
    assert gates_for(oracle_case(harness, "S01"), proposal(setup, ResultCode.CONSISTENT))[
        "G3"
    ].passed


def test_g4_conflicts_needs_a_hard_conflict_the_evidence_backs(harness):
    setup = oracle_case(harness, "S23")
    assert not gates_for(setup, proposal(setup, ResultCode.CONFLICTS, hard=("HC1",)))["G4"].passed
    setup = oracle_case(harness, "S15")
    assert not gates_for(setup, proposal(setup, ResultCode.CONFLICTS, hard=("HC1",)))["G4"].passed
    assert gates_for(setup, proposal(setup, ResultCode.CONFLICTS, hard=("HC5",)))["G4"].passed


def test_g5_refuses_verdicts_and_advice(harness):
    setup = oracle_case(harness, "S15")
    for wording in ("This is a scam.", "It is a clone of the site.", "We recommend you wait."):
        gate = gates_for(
            setup, proposal(setup, ResultCode.CONFLICTS, hard=("HC5",), explanation=wording)
        )["G5"]
        assert not gate.passed, wording


def test_g5_reads_claims_as_well_as_the_explanation(harness):
    setup = oracle_case(harness, "S15")
    contact = setup.board.live_findings("contact_assessment")[0]
    claim = claim_on(contact, "This is a fake website.")
    gates = gates_for(setup, proposal(setup, ResultCode.CONFLICTS, claim, hard=("HC5",)))
    assert not gates["G5"].passed and "fake" in gates["G5"].detail


def test_g6_fixes_a_dfsa_deep_link_rather_than_vetoing(harness):
    setup = oracle_case(harness, "S15")
    link = "https://www.dfsa" + ".ae/alerts/2026/some-alert"
    text = f"See {link} for details."
    gate = gates_for(setup, proposal(setup, ResultCode.CONFLICTS, hard=("HC5",), explanation=text))[
        "G6"
    ]
    assert gate.passed and "1 link(s) fixed" in gate.detail
    assert clean_links(text) == f"See {DFSA_HOMEPAGE} for details."


def test_g6_leaves_the_homepage_alone():
    assert clean_links(f"Check {DFSA_HOMEPAGE} directly.") == f"Check {DFSA_HOMEPAGE} directly."


def test_g7_every_relevant_regulator_must_be_disclosed(harness):
    setup = oracle_case(harness, "S15")
    undisclosed = proposal(setup, ResultCode.CONFLICTS, hard=("HC5",)).model_copy(
        update={"regulators": ()}
    )
    gate = gates_for(setup, undisclosed)["G7"]
    assert not gate.passed and "CMA" in gate.detail


def test_g8_a_proposal_cannot_be_more_reassuring_than_the_policy(harness):
    setup = oracle_case(harness, "S23")
    gate = gates_for(setup, proposal(setup, ResultCode.CONSISTENT))["G8"]
    assert not gate.passed and "UNVERIFIED" in gate.detail


def test_being_more_cautious_than_the_policy_is_only_advisory(harness):
    setup = oracle_case(harness, "S15")
    cautious = proposal(setup, ResultCode.UNVERIFIED, reasons=("U3",))
    decision = derive_decision(setup.env, today=FICTION_DATE)
    assert all(g.passed for g in run_gates(setup.env, cautious, decision))
    assert is_under_call(cautious, decision)
    assert not is_under_call(proposal(setup, ResultCode.CONFLICTS, hard=("HC5",)), decision)
