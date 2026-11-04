"""The Verifier's deterministic gates, G1–G8 (§6.8). They run before any model check."""

from __future__ import annotations

# A finding's assertion is a union. Each rule picks findings by type first, so attributes are safe.
# mypy: disable-error-code="union-attr"
import re

from tessera.agents.base import AgentEnv
from tessera.governance.language import lint_text
from tessera.governance.links import DFSA_DEEP_LINK, DFSA_HOMEPAGE, find_dfsa_deep_links
from tessera.governance.policies import LanguagePolicy
from tessera.orchestration.decision import PolicyDecision, relevant_regulators
from tessera.orchestration.support import ClaimChecker
from tessera.protocol.claims import needs_evidence
from tessera.protocol.common import ResultCode
from tessera.protocol.results import GateResult, ProposedResult

_DFSA_LINK = re.compile(rf"(?:https?://)?(?:www\.)?{DFSA_DEEP_LINK.pattern}", re.IGNORECASE)


def texts_of(proposal: ProposedResult) -> list[str]:
    """Everything in a proposal that a person would read."""
    return [
        proposal.explanation,
        *(claim.text for claim in proposal.claims),
        *(coverage.rationale for coverage in proposal.regulators),
    ]


def clean_links(text: str) -> str:
    """Replace any DFSA deep link with the homepage (gate G6's automatic fix)."""
    return _DFSA_LINK.sub(DFSA_HOMEPAGE, text)


def _gate(gate: str, problems: list[str], passed_detail: str = "") -> GateResult:
    return GateResult(
        gate=gate, passed=not problems, detail="; ".join(problems)[:600] or passed_detail
    )


def _evidence_exists(env: AgentEnv, proposal: ProposedResult) -> GateResult:
    problems: list[str] = []
    for index, claim in enumerate(proposal.claims):
        unknown = env.board.unknown_evidence(claim.evidence_ids)
        if unknown:
            problems.append(f"claim {index} cites evidence no tool created")
        elif not claim.evidence_ids and needs_evidence(claim.assertion):
            problems.append(f"claim {index} cites no evidence")
    return _gate("G1", problems)


def _evidence_supports(env: AgentEnv, proposal: ProposedResult) -> GateResult:
    checker = ClaimChecker(env.board, env.ctx.sources, env.facts_for)
    problems: list[str] = []
    for index, claim in enumerate(proposal.claims):
        finding = env.board.findings.get(claim.finding_id)
        if finding is None or not finding.is_live:
            problems.append(f"claim {index} rests on a finding that no longer stands")
        elif finding.assertion != claim.assertion:
            problems.append(f"claim {index} differs from its finding")
        else:
            problems += [f"claim {index}: {problem}" for problem in checker.problems(finding)]
    return _gate("G2", problems)


def _consistent_holds(proposal: ProposedResult, decision: PolicyDecision) -> GateResult:
    if proposal.result is not ResultCode.CONSISTENT:
        return _gate("G3", [], "not applicable")
    failed = [name for name, held in decision.conditions.items() if not held]
    problems = [f"conditions not met: {', '.join(failed)}"] if failed else []
    if decision.unverified_reasons:
        problems.append(f"reasons apply: {', '.join(decision.unverified_reasons)}")
    return _gate("G3", problems)


def _conflicts_holds(proposal: ProposedResult, decision: PolicyDecision) -> GateResult:
    if proposal.result is not ResultCode.CONFLICTS:
        return _gate("G4", [], "not applicable")
    proposed = set(proposal.hard_conflicts)
    if proposed & set(decision.hard_conflict_ids):
        return _gate("G4", [])
    return _gate("G4", ["no proposed hard conflict is backed by valid evidence"])


def _language(proposal: ProposedResult, policy: LanguagePolicy) -> GateResult:
    found = [v.term for text in texts_of(proposal) for v in lint_text(text, policy)]
    problems = [f"banned wording: {', '.join(sorted(set(found)))}"] if found else []
    if not policy.disclaimer.strip():
        problems.append("the disclaimer is missing")
    return _gate("G5", problems)


def _links(proposal: ProposedResult) -> GateResult:
    """Never fails: the report replaces these links. The count is kept for telemetry."""
    count = sum(len(find_dfsa_deep_links(text)) for text in texts_of(proposal))
    return GateResult(gate="G6", passed=True, detail=f"{count} link(s) fixed" if count else "")


def _coverage(env: AgentEnv, proposal: ProposedResult) -> GateResult:
    listed = {coverage.regulator: coverage for coverage in proposal.regulators}
    problems = [
        f"{regulator} is relevant but not disclosed"
        for regulator in sorted(relevant_regulators(env) - set(listed))
    ]
    return _gate("G7", problems)


def _policy(proposal: ProposedResult, decision: PolicyDecision) -> GateResult:
    """G8. The opposite mistake, being more cautious than needed, is an advisory under-call."""
    if proposal.result is ResultCode.CONSISTENT and decision.result is not ResultCode.CONSISTENT:
        return _gate("G8", [f"the policy supports {decision.result.value}"])
    return _gate("G8", [])


def is_under_call(proposal: ProposedResult, decision: PolicyDecision) -> bool:
    return proposal.result is ResultCode.UNVERIFIED and decision.result is not ResultCode.UNVERIFIED


def run_gates(
    env: AgentEnv, proposal: ProposedResult, decision: PolicyDecision
) -> tuple[GateResult, ...]:
    return (
        _evidence_exists(env, proposal),
        _evidence_supports(env, proposal),
        _consistent_holds(proposal, decision),
        _conflicts_holds(proposal, decision),
        _language(proposal, env.language),
        _links(proposal),
        _coverage(env, proposal),
        _policy(proposal, decision),
    )
