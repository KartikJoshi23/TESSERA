"""The final result, and the report rendered from it (§12.1).

:func:`compose_final` runs at the end of every case. A result stays as proposed only if the Verifier
approved it, or if the Verifier is switched off. Otherwise it becomes "Could not verify", so a veto
can never move a result toward "Consistent".

:func:`render_report` runs when someone asks to see a case. The stored result is masked. A report is
built on demand, and is the only place DFSA values and dates appear: they are resolved locally, in
research mode, and the report is never written to the event log.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from tessera.agents.base import AgentEnv
from tessera.blackboard.board import Blackboard
from tessera.data.schemas import DfsaAlertFact
from tessera.governance.language import lint_text
from tessera.governance.links import find_dfsa_deep_links
from tessera.governance.policies import DecisionPolicy, LanguagePolicy
from tessera.orchestration.decision import PolicyDecision
from tessera.orchestration.gates import clean_links, texts_of
from tessera.protocol.common import AgentId, ResultCode
from tessera.protocol.evidence import EvidenceKind, EvidenceRecord
from tessera.protocol.results import FinalResult, ProposedResult, RegulatorCoverage
from tessera.tools import ToolContext

_WITHHELD = "The written explanation was withheld. The claims below show what the records say."


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceChip(_Frozen):
    evidence_id: str
    source: str
    kind: str
    as_of: date | None = None
    #: The date on the record itself, such as an alert's date, where one is known.
    dated: date | None = None
    link: str | None = None


class ReportClaim(_Frozen):
    text: str
    evidence: tuple[EvidenceChip, ...] = ()


class SourceDate(_Frozen):
    source: str
    as_of: date | None = None


class VerifyLink(_Frozen):
    regulator: str
    link: str


class RuleLine(_Frozen):
    id: str
    text: str


class CaseReport(_Frozen):
    """Everything §12.1 requires. Items 1 to 8 appear in that order."""

    result: ResultCode
    wording: str
    explanation: str
    hard_conflicts: tuple[RuleLine, ...] = ()
    unverified_reasons: tuple[RuleLine, ...] = ()
    claims: tuple[ReportClaim, ...] = ()
    regulators: tuple[RegulatorCoverage, ...] = ()
    sources: tuple[SourceDate, ...] = ()
    how_to_verify: tuple[VerifyLink, ...] = ()
    disclaimer: str
    synthetic: bool = True
    case_id: str
    condition: str
    mode: str


# ---------------------------------------------------------------------- the final result


def _fallback_explanation(reasons: tuple[str, ...], policy: DecisionPolicy) -> str:
    """Plain wording from the policy, for when no approved explanation exists."""
    texts = {rule.id: rule.text for rule in policy.unverified_reasons}
    listed = " ".join(texts[reason] for reason in reasons if reason in texts)
    return f"The offer could not be confirmed against the official record. {listed}".strip()


def _usable_explanation(proposal: ProposedResult, language: LanguagePolicy) -> bool:
    return bool(proposal.explanation.strip()) and not lint_text(proposal.explanation, language)


def compose_final(
    env: AgentEnv,
    decision: PolicyDecision,
    *,
    verifier_on: bool,
    detail: dict[str, Any] | None = None,
) -> FinalResult:
    board = env.board
    proposal = board.proposals[-1] if board.proposals else None
    last = board.verifier_reports[-1] if board.verifier_reports else None
    approved = proposal is not None and (
        not verifier_on
        or (
            last is not None
            and last.decision == "APPROVE"
            and last.proposal_version == proposal.version
        )
    )
    meter = env.runner.meter
    extra: dict[str, Any] = {
        "policy_result": decision.result.value,
        "under_call": bool(last and last.under_call),
        "conditions": decision.conditions,
        "requests": meter.requests,
        "prompt_tokens": meter.prompt_tokens,
        "completion_tokens": meter.completion_tokens,
        "requests_by_agent": dict(meter.by_agent),
        **(detail or {}),
    }
    if proposal is not None and approved:
        return _final_from_proposal(env, proposal, decision, extra, verifier_on=verifier_on)
    # A proposal that was vetoed, or no proposal at all, can only be "Could not verify".
    reasons = list(decision.unverified_reasons)
    if proposal is None:
        reasons.append("U7")
    unique = tuple(dict.fromkeys(reasons)) or ("U7",)
    return FinalResult(
        result=ResultCode.UNVERIFIED,
        wording=env.language.result_strings[ResultCode.UNVERIFIED.value],
        explanation=_fallback_explanation(unique, env.decision),
        proposal_version=proposal.version if proposal else None,
        unverified_reasons=unique,
        regulators=proposal.regulators if proposal else (),
        disclaimer=env.language.disclaimer,
        detail=extra,
    )


def _stated_conflicts(
    proposal: ProposedResult, decision: PolicyDecision, *, verifier_on: bool
) -> tuple[str, ...]:
    """Every hard conflict the evidence backs, and no other.

    Gate G4 needs only one to hold, so a proposal can miss some or add others. With the Verifier
    off nothing checks them, which is the point of that ablation.
    """
    if proposal.result is not ResultCode.CONFLICTS:
        return ()
    return decision.hard_conflict_ids if verifier_on else proposal.hard_conflicts


def _final_from_proposal(
    env: AgentEnv,
    proposal: ProposedResult,
    decision: PolicyDecision,
    extra: dict[str, Any],
    *,
    verifier_on: bool,
) -> FinalResult:
    code = proposal.result
    fixed = sum(len(find_dfsa_deep_links(text)) for text in texts_of(proposal))
    if fixed:
        env.board.record("verifier.autofix", AgentId.ORC, {"gate": "G6", "links": fixed})
    # The linter runs on every result, even when the Verifier is switched off for an ablation.
    reasons: tuple[str, ...] = ()
    if code is ResultCode.UNVERIFIED:
        derived = decision.unverified_reasons if verifier_on else ()
        reasons = derived or proposal.unverified_reasons
    if _usable_explanation(proposal, env.language):
        explanation = clean_links(proposal.explanation)
    else:
        env.board.record("report.wording_replaced", AgentId.ORC, {"version": proposal.version})
        explanation = (
            _fallback_explanation(reasons, env.decision)
            if code is ResultCode.UNVERIFIED
            else _WITHHELD
        )
    claims = tuple(
        claim
        if not lint_text(claim.text, env.language)
        else claim.model_copy(update={"text": f"See {claim.finding_id}."})
        for claim in (c.model_copy(update={"text": clean_links(c.text)}) for c in proposal.claims)
    )
    return FinalResult(
        result=code,
        wording=env.language.result_strings[code.value],
        explanation=explanation,
        proposal_version=proposal.version,
        hard_conflicts=_stated_conflicts(proposal, decision, verifier_on=verifier_on),
        unverified_reasons=reasons,
        claims=claims,
        regulators=proposal.regulators,
        disclaimer=env.language.disclaimer,
        detail=extra,
    )


# ---------------------------------------------------------------------- the report


def _record_date(ctx: ToolContext, record: EvidenceRecord) -> date | None:
    """The date on a list record. A DFSA alert's date is looked up here, and is never stored."""
    if record.kind is EvidenceKind.ALERT_ENTRY and ctx.registry.restricted_allowed:
        row = ctx.registry.table(record.source_id).get(record.locator)
        return row.alert_date if isinstance(row, DfsaAlertFact) else None
    value = record.fields.get("warning_date") or record.fields.get("date_listed")
    return date.fromisoformat(value) if value else None


def _source_name(ctx: ToolContext, record: EvidenceRecord) -> str:
    policy = ctx.sources.sources.get(record.source_id)
    return policy.name if policy else record.source_id


def _chip(ctx: ToolContext, record: EvidenceRecord) -> EvidenceChip:
    return EvidenceChip(
        evidence_id=record.evidence_id,
        source=_source_name(ctx, record),
        kind=record.kind.value,
        as_of=record.snapshot_date,
        dated=_record_date(ctx, record),
        link=record.display_link,
    )


def _lines(ids: tuple[str, ...], rules: Any) -> tuple[RuleLine, ...]:
    texts = {rule.id: rule.text for rule in rules}
    return tuple(RuleLine(id=rule_id, text=texts.get(rule_id, rule_id)) for rule_id in ids)


def _how_to_verify(ctx: ToolContext, regulators: tuple[RegulatorCoverage, ...]) -> list[VerifyLink]:
    """The regulator's own site. The source policy holds the only link the DFSA allows."""
    links: dict[str, str] = {}
    for policy in ctx.sources.sources.values():
        links.setdefault(policy.regulator, policy.homepage)
    return [
        VerifyLink(regulator=coverage.regulator, link=links[coverage.regulator])
        for coverage in regulators
        if coverage.regulator in links
    ]


def render_report(board: Blackboard, ctx: ToolContext) -> CaseReport:
    """Build the report for a finished case. Masked values are restored here, locally."""
    final, case = board.final, board.case
    if final is None or case is None:
        raise ValueError("the case has not finished")
    evidence = board.evidence
    claims = [
        ReportClaim(
            text=claim.text,
            evidence=tuple(_chip(ctx, evidence[e]) for e in claim.evidence_ids if e in evidence),
        )
        for claim in final.claims
    ]
    sources: dict[str, date | None] = {}
    for record in evidence.values():
        if record.kind is not EvidenceKind.RULE_CARD and record.snapshot_id is not None:
            sources[_source_name(ctx, record)] = record.snapshot_date
    report = CaseReport(
        result=final.result,
        wording=final.wording,
        explanation=final.explanation,
        hard_conflicts=_lines(final.hard_conflicts, ctx.decision.hard_conflicts),
        unverified_reasons=_lines(final.unverified_reasons, ctx.decision.unverified_reasons),
        claims=tuple(claims),
        regulators=final.regulators,
        sources=tuple(SourceDate(source=name, as_of=day) for name, day in sources.items()),
        how_to_verify=tuple(_how_to_verify(ctx, final.regulators)),
        disclaimer=final.disclaimer,
        case_id=case.case_id,
        condition=case.condition.value,
        mode=case.mode,
    )
    return CaseReport.model_validate(board.gateway.unmask_payload(report.model_dump(mode="json")))
