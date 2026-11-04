"""The blackboard: event sourcing, masking at the write path, and the protocol rules."""

import pytest

from tessera.blackboard.board import Blackboard
from tessera.blackboard.store import EventStore
from tessera.blackboard.views import ViewOptions, regulator_view, verifier_view
from tessera.config.settings import Mode
from tessera.errors import RestrictedValueLeak, SyntheticInputRejected
from tessera.governance.masking import MaskingGateway, RestrictedValue
from tessera.governance.synthetic_gate import OfferInput
from tessera.protocol.case import SystemCondition, strip_gold
from tessera.protocol.claims import RegisterNoMatch, Relevance, ZoneSignal
from tessera.protocol.common import AgentId, ResultCode
from tessera.protocol.conflicts import ConflictStatus, ConflictType
from tessera.protocol.evidence import EvidenceKind, mint_evidence
from tessera.protocol.findings import FindingStatus
from tessera.protocol.messages import MessageDraft, Performative, ProtocolViolation
from tessera.protocol.results import ProposedResult, ResultClaim

OFFER = "Lumen Crest Capital (DIFC) Limited invites you to lumencrest-capital.example today."
GATEWAY = MaskingGateway(
    [
        RestrictedValue("Lumen Crest Capital (DIFC) Limited", "firm_name"),
        RestrictedValue("lumencrest-capital.example", "domain"),
    ]
)


def open_board(store: EventStore | None = None) -> Blackboard:
    return Blackboard.open_case(
        store or EventStore(),
        case_id="c1",
        offer=OfferInput(text=OFFER, synthetic=True, corpus_item_id="X"),
        condition=SystemCondition.CREW_FULL,
        mode=Mode.RESEARCH_INTERNAL,
        gateway=GATEWAY,
    )


def rule_evidence(board: Blackboard) -> str:
    record = mint_evidence(
        case_id="c1",
        source_id="rule_cards",
        kind=EvidenceKind.RULE_CARD,
        locator="JUR-01",
        fields={"rule_id": "JUR-01"},
        minted_by="get_rule_card",
    )
    board.add_evidence([record])
    return record.evidence_id


def challenge(
    board: Blackboard, finding_id: str, sender=AgentId.VARA, evidence=(), rules=("JUR-01",)
):
    return board.send(
        MessageDraft(
            sender=sender,
            recipients=(AgentId.JUR,),
            performative=Performative.CHALLENGE,
            refs=(finding_id,),
            evidence_ids=tuple(evidence),
            rule_ids=tuple(rules),
            body={"question": "Why?"},
        )
    )


def relevance(status="excluded"):
    return Relevance(regulator="VARA", status=status, rule_ids=("JUR-01",))


# ------------------------------------------------------------------- opening a case


def test_a_case_is_stored_masked():
    board = open_board()
    assert board.case is not None
    assert GATEWAY.leaked_values(board.case.offer_text) == []
    assert "(DIFC) Limited" in board.case.offer_text
    domain = next(p for p in board.case.contact_points if p.kind.value == "domain")
    assert domain.normalized.startswith("⟦R:DOMAIN")


def test_real_messages_never_open_a_case():
    with pytest.raises(SyntheticInputRejected):
        Blackboard.open_case(
            EventStore(),
            case_id="c1",
            offer=OfferInput(text="real message", synthetic=False, corpus_item_id="X"),
            condition=SystemCondition.CREW_FULL,
            mode=Mode.RESEARCH_INTERNAL,
        )


def test_gold_fields_are_stripped_from_dataset_items():
    item = {"id": "S1", "text": "x", "gold_label": "CONFLICTS", "gold_reasons": ["HC1"]}
    assert strip_gold(item) == {"id": "S1", "text": "x"}


# ------------------------------------------------------------------- the write path


def test_replaying_the_log_rebuilds_the_same_state():
    store = EventStore()
    board = open_board(store)
    evidence = rule_evidence(board)
    finding = board.post_finding(AgentId.JUR, relevance(), evidence_ids=[evidence])
    message = challenge(board, finding.finding_id)
    board.revise_finding(
        reply_to=message.msg_id,
        sender=AgentId.JUR,
        assertion=relevance("possible"),
        rule_ids=("JUR-01",),
        rationale="The DIFC address is only a claim.",
    )
    conflict = board.add_conflict(ConflictType.C1, [finding.finding_id])
    board.resolve_conflict(conflict.conflict_id, outcome="merged", precedence_rule="P5")
    assert Blackboard.replay(store, "c1", gateway=GATEWAY).snapshot() == board.snapshot()


def test_nothing_restricted_can_be_written():
    board = open_board()
    with pytest.raises(RestrictedValueLeak) as caught:
        board.record("agent.note", AgentId.ORC, {"text": "see lumencrest-capital.example"})
    assert "lumencrest" not in str(caught.value)  # the error never repeats the value


def test_evidence_fields_are_masked_when_stored():
    board = open_board()
    record = mint_evidence(
        case_id="c1",
        source_id="cma_warnings",
        kind=EvidenceKind.NO_MATCH,
        locator="no-match",
        fields={"query": {"domain": "lumencrest-capital.example"}},
        minted_by="reverse_contact_lookup",
    )
    board.add_evidence([record])
    stored = board.evidence[record.evidence_id]
    assert stored.fields["query"]["domain"].startswith("⟦R:DOMAIN")


def test_unknown_evidence_is_kept_and_flagged_not_hidden():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance(), evidence_ids=["E-made-up"])
    assert finding.unknown_evidence_ids == ("E-made-up",)


def test_finding_text_from_a_model_is_masked():
    board = open_board()
    finding = board.post_finding(
        AgentId.JUR,
        ZoneSignal(zone="DIFC", basis="address"),
        rationale="As stated on lumencrest-capital.example",
    )
    assert GATEWAY.leaked_values(finding.rationale) == []


# ------------------------------------------------------------------- protocol rules


def test_a_challenge_must_cite_something():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    with pytest.raises(ProtocolViolation) as caught:
        challenge(board, finding.finding_id, rules=())
    assert caught.value.code == "challenge_without_grounds"
    assert board.rejections[-1]["code"] == "challenge_without_grounds"


def test_a_challenge_goes_to_the_findings_author():
    board = open_board()
    finding = board.post_finding(AgentId.CMA, relevance())
    with pytest.raises(ProtocolViolation) as caught:
        challenge(board, finding.finding_id)
    assert caught.value.code == "wrong_recipient"


def test_an_agent_cannot_challenge_itself():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    with pytest.raises(ProtocolViolation) as caught:
        challenge(board, finding.finding_id, sender=AgentId.JUR)
    assert caught.value.code == "self_challenge"


def test_a_challenge_marks_the_finding_and_reaches_the_inbox():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    message = challenge(board, finding.finding_id)
    assert board.findings[finding.finding_id].status is FindingStatus.CHALLENGED
    assert [m.msg_id for m in board.inbox(AgentId.JUR)] == [message.msg_id]


def test_revising_without_a_citation_is_a_conformity_flag():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    message = challenge(board, finding.finding_id)
    with pytest.raises(ProtocolViolation):
        board.revise_finding(
            reply_to=message.msg_id, sender=AgentId.JUR, assertion=relevance("possible")
        )
    assert len(board.conformity_flags) == 1
    assert board.findings[finding.finding_id].assertion.status == "excluded"  # unchanged


def test_a_cited_revision_makes_a_new_version_and_keeps_the_old_one():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    message = challenge(board, finding.finding_id)
    revised = board.revise_finding(
        reply_to=message.msg_id,
        sender=AgentId.JUR,
        assertion=relevance("possible"),
        rule_ids=("JUR-01",),
    )
    assert revised.version == 2 and revised.status is FindingStatus.ACTIVE
    history = board.history[finding.finding_id]
    assert [f.status for f in history] == [FindingStatus.SUPERSEDED, FindingStatus.ACTIVE]
    assert board.inbox(AgentId.JUR) == []


def test_a_revision_cannot_change_the_assertion_type():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    message = challenge(board, finding.finding_id)
    with pytest.raises(ProtocolViolation) as caught:
        board.revise_finding(
            reply_to=message.msg_id,
            sender=AgentId.JUR,
            assertion=RegisterNoMatch(regulator="VARA"),
            rule_ids=("JUR-01",),
        )
    assert caught.value.code == "revision_changes_type"


def test_conceding_withdraws_the_finding():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    message = challenge(board, finding.finding_id)
    board.send(
        MessageDraft(
            sender=AgentId.JUR,
            recipients=(AgentId.VARA,),
            performative=Performative.CONCEDE,
            refs=(finding.finding_id,),
            in_reply_to=message.msg_id,
        )
    )
    assert board.findings[finding.finding_id].status is FindingStatus.WITHDRAWN
    assert board.live_findings("relevance") == []


def test_only_the_reconciler_resolves_and_it_must_name_a_rule():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    conflict = board.add_conflict(ConflictType.C1, [finding.finding_id])
    with pytest.raises(ProtocolViolation) as caught:
        board.resolve_conflict(conflict.conflict_id, outcome="upheld", precedence_rule="because")
    assert caught.value.code == "no_precedence_rule"
    with pytest.raises(ProtocolViolation) as caught:
        board.send(
            MessageDraft(
                sender=AgentId.JUR,
                recipients=(AgentId.ORC,),
                performative=Performative.RESOLVE,
                refs=(conflict.conflict_id,),
                body={"precedence_rule": "P1"},
            )
        )
    assert caught.value.code == "reconciler_only"
    assert board.conflicts[conflict.conflict_id].status is ConflictStatus.OPEN


def test_only_the_verifier_can_veto():
    board = open_board()
    with pytest.raises(ProtocolViolation) as caught:
        board.send(
            MessageDraft(
                sender=AgentId.REC,
                recipients=(AgentId.ORC,),
                performative=Performative.VETO,
            )
        )
    assert caught.value.code == "verifier_only"


def test_rationales_are_capped_at_60_words():
    board = open_board()
    finding = board.post_finding(AgentId.JUR, relevance())
    with pytest.raises(ProtocolViolation) as caught:
        board.send(
            MessageDraft(
                sender=AgentId.VARA,
                recipients=(AgentId.JUR,),
                performative=Performative.CHALLENGE,
                refs=(finding.finding_id,),
                rule_ids=("JUR-01",),
                body={"question": "Why?"},
                rationale="word " * 61,
            )
        )
    assert caught.value.code == "rationale_too_long"


def test_try_send_logs_a_rejection_without_raising():
    board = open_board()
    draft = MessageDraft(
        sender=AgentId.JUR, recipients=(AgentId.CMA,), performative=Performative.REQUEST
    )
    assert board.try_send(draft) is None
    assert board.rejections[-1]["code"] == "bad_request"


# ------------------------------------------------------------------- views


def test_the_silo_ablation_hides_other_agents():
    board = open_board()
    board.post_finding(AgentId.JUR, relevance())
    board.post_finding(AgentId.DFSA, Relevance(regulator="DFSA", status="primary"))
    shared = regulator_view(board, AgentId.VARA)
    silo = regulator_view(board, AgentId.VARA, ViewOptions(share=False))
    assert shared["jurisdiction_findings"] and shared["other_regulators"]
    assert "jurisdiction_findings" not in silo and "other_regulators" not in silo


def test_regulators_see_what_others_found_but_not_how_they_argued():
    board = open_board()
    board.post_finding(
        AgentId.DFSA, Relevance(regulator="DFSA", status="primary"), rationale="secret reasoning"
    )
    view = regulator_view(board, AgentId.VARA)
    assert "rationale" not in view["other_regulators"][0]


def test_the_verifier_never_sees_agents_prose():
    board = open_board()
    finding = board.post_finding(
        AgentId.JUR, relevance(), rationale="the persuasive reasoning of an agent"
    )
    proposal = board.post_proposal(
        ProposedResult(
            version=1,
            author=AgentId.REC,
            result=ResultCode.UNVERIFIED,
            unverified_reasons=("U1",),
            claims=(
                ResultClaim(
                    finding_id=finding.finding_id,
                    assertion=finding.assertion,
                    text="A claim.",
                ),
            ),
            explanation="An explanation.",
        )
    )
    view = verifier_view(board, proposal)
    assert "persuasive" not in str(view)
    assert view["claims"][0]["assertion"]["type"] == "relevance"
