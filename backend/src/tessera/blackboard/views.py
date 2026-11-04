"""What each agent sees (implementation-plan.md §6.9).

Views are the information-flow control of the crew:

* No view holds gold labels or any agent's raw reasoning.
* The Verifier never sees the Reconciler's rationale or other agents' prose. It sees typed claims
  and the full evidence store, so its independence is structural, not a matter of instruction.
* ``ViewOptions.share`` is the ablation switch: with it off, agents see only the offer.

Restricted evidence holds row references only. ``facts_for`` resolves what a model may learn from
a reference, locally: identifiers and tool-computed relations, never recorded wording or dates.
They appear only in the outgoing prompt, which is masked, and are never persisted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tessera.blackboard.board import Blackboard
from tessera.protocol.common import AgentId
from tessera.protocol.evidence import EvidenceRecord
from tessera.protocol.findings import Finding
from tessera.protocol.messages import Message
from tessera.protocol.results import ProposedResult

FactsFor = Callable[[EvidenceRecord], dict[str, Any]]


@dataclass(frozen=True)
class ViewOptions:
    #: False is the CREW-SILO ablation: no agent sees another agent's findings.
    share: bool = True


SHARED = ViewOptions()


def _no_facts(_: EvidenceRecord) -> dict[str, Any]:
    return {}


def evidence_view(record: EvidenceRecord, facts_for: FactsFor = _no_facts) -> dict[str, Any]:
    view: dict[str, Any] = {
        "evidence_id": record.evidence_id,
        "source": record.source_id,
        "kind": record.kind.value,
        "fields": record.fields,
    }
    if record.snapshot_date:
        view["as_of"] = record.snapshot_date.isoformat()
    if record.restricted:
        view["facts"] = facts_for(record)
    return view


def finding_view(finding: Finding, *, rationale: bool = True) -> dict[str, Any]:
    view: dict[str, Any] = {
        "finding_id": finding.finding_id,
        "author": finding.author.value,
        "assertion": finding.assertion.model_dump(mode="json", exclude_none=True),
        "confidence": finding.confidence,
        "evidence_ids": list(finding.evidence_ids),
        "status": finding.status.value,
    }
    if finding.version > 1:
        view["version"] = finding.version
    if rationale and finding.rationale:
        view["rationale"] = finding.rationale
    return view


def message_view(message: Message) -> dict[str, Any]:
    view: dict[str, Any] = {
        "message_id": message.msg_id,
        "from": message.sender.value,
        "type": message.performative.value,
        "about": list(message.refs),
        "evidence_ids": list(message.evidence_ids),
        "rule_ids": list(message.rule_ids),
    }
    view.update({k: v for k, v in message.body.items() if v})
    if message.rationale:
        view["rationale"] = message.rationale
    return view


def contact_views(board: Blackboard) -> list[dict[str, Any]]:
    assert board.case is not None
    return [
        {
            "cp_id": point.cp_id,
            "kind": point.kind.value,
            "value": point.normalized,
            "role": point.role.value,
            **({"detail": point.detail} if point.detail else {}),
        }
        for point in board.case.contact_points
    ]


def _inbox(board: Blackboard, agent: AgentId) -> list[dict[str, Any]]:
    return [message_view(m) for m in board.inbox(agent)]


def _findings_by(board: Blackboard, *authors: AgentId, rationale: bool = True) -> list[dict]:
    return [
        finding_view(f, rationale=rationale) for f in board.live_findings() if f.author in authors
    ]


def jurisdiction_view(board: Blackboard, options: ViewOptions = SHARED) -> dict[str, Any]:
    view: dict[str, Any] = {
        "contact_points": contact_views(board),
        "your_findings": _findings_by(board, AgentId.JUR),
        "inbox": _inbox(board, AgentId.JUR),
    }
    if options.share:
        view["regulator_relevance_opinions"] = [
            finding_view(f) for f in board.live_findings("relevance") if f.author is not AgentId.JUR
        ]
    return view


def regulator_view(
    board: Blackboard, agent: AgentId, options: ViewOptions = SHARED
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "contact_points": contact_views(board),
        "your_findings": _findings_by(board, agent),
        "inbox": _inbox(board, agent),
    }
    if options.share:
        view["jurisdiction_findings"] = _findings_by(board, AgentId.JUR)
        others = [a for a in (AgentId.CMA, AgentId.DFSA, AgentId.VARA) if a is not agent]
        # Summaries only: what other regulators found, not how they argued it.
        view["other_regulators"] = _findings_by(board, *others, rationale=False)
    return view


def clone_view(board: Blackboard, options: ViewOptions = SHARED) -> dict[str, Any]:
    view: dict[str, Any] = {
        "contact_points": contact_views(board),
        "your_findings": _findings_by(board, AgentId.CLN),
        "inbox": _inbox(board, AgentId.CLN),
    }
    if options.share:
        wanted = {"register_match", "licence_status", "licence_scope", "alert_hit"}
        view["regulator_findings"] = [
            finding_view(f, rationale=False)
            for f in board.live_findings()
            if f.assertion.type in wanted
        ]
    return view


def reconciler_view(board: Blackboard, facts_for: FactsFor = _no_facts) -> dict[str, Any]:
    return {
        "findings": [finding_view(f) for f in board.live_findings()],
        "contact_points": contact_views(board),
        "messages": [
            message_view(m)
            for m in board.messages
            if m.performative.value not in {"INFORM", "RESOLVE"}
        ],
        "open_conflicts": [
            c.model_dump(mode="json", exclude={"resolution_id"}) for c in board.open_conflicts()
        ],
        "resolutions": [r.model_dump(mode="json") for r in board.resolutions.values()],
        "evidence": [evidence_view(e, facts_for) for e in board.evidence.values()],
        "failures": board.failures,
    }


def verifier_view(
    board: Blackboard, proposal: ProposedResult, facts_for: FactsFor = _no_facts
) -> dict[str, Any]:
    """Typed claims and the *full* evidence store, with no agent's prose (§6.8)."""
    return {
        "proposed_result": proposal.result.value,
        "claims": [
            {
                "claim_index": index,
                "text": claim.text,
                "assertion": claim.assertion.model_dump(mode="json", exclude_none=True),
                "evidence_ids": list(claim.evidence_ids),
            }
            for index, claim in enumerate(proposal.claims)
        ],
        "explanation": proposal.explanation,
        "contact_points": contact_views(board),
        "evidence": [evidence_view(e, facts_for) for e in board.evidence.values()],
    }
