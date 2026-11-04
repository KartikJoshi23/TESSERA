"""What coordination did in a case, and what it cost, derived from the event log (§6.11).

Everything here is read from events, so it can be worked out again for any past case. Revisions are
listed, not judged: whether one was a harmful flip takes a gold label, so the evaluation decides
that (§11.3). The trace bundle holds masked events and evidence references, so it holds no DFSA
value, and it can be kept with a run's results.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

from tessera.blackboard.board import Blackboard
from tessera.blackboard.store import Event
from tessera.protocol.conflicts import ConflictStatus
from tessera.protocol.messages import Performative


def _spending(events: Sequence[Event]) -> dict[str, dict[str, int]]:
    """Requests and tokens per phase, which is what each mechanism costs."""
    spent: dict[str, Counter[str]] = defaultdict(Counter)
    phase = "intake"
    for event in events:
        if event.type == "round.started":
            phase = event.payload["phase"]
        elif event.type == "llm.response":
            usage = event.usage or {}
            spent[phase]["requests"] += 1
            spent[phase]["prompt_tokens"] += usage.get("prompt_tokens", 0)
            spent[phase]["completion_tokens"] += usage.get("completion_tokens", 0)
    return {name: dict(counts) for name, counts in spent.items()}


def _revisions(board: Blackboard) -> list[dict[str, Any]]:
    """Every change of position, for the evaluation to judge against gold."""
    found = []
    for finding_id, versions in board.history.items():
        for before, after in pairwise(versions):
            found.append(
                {
                    "finding_id": finding_id,
                    "author": after.author.value,
                    "type": after.assertion.type,
                    "before": before.assertion.model_dump(mode="json"),
                    "after": after.assertion.model_dump(mode="json"),
                }
            )
    return found


def case_telemetry(board: Blackboard, events: Sequence[Event]) -> dict[str, Any]:
    sent = Counter(message.performative.value for message in board.messages)
    conflicts = list(board.conflicts.values())
    challenges = sent[Performative.CHALLENGE.value]
    revisions = _revisions(board)
    reports = board.verifier_reports
    return {
        "conflicts": {
            "total": len(conflicts),
            "by_type": dict(Counter(c.type.value for c in conflicts)),
            "by_detector": dict(Counter(c.detected_by for c in conflicts)),
            "by_status": dict(Counter(c.status.value for c in conflicts)),
            "unresolved": sum(
                c.status in (ConflictStatus.OPEN, ConflictStatus.UNRESOLVED) for c in conflicts
            ),
        },
        "challenges": {
            "sent": challenges,
            "revisions": sent[Performative.REVISE.value],
            "rebuttals": sent[Performative.REBUT.value],
            "concessions": sent[Performative.CONCEDE.value],
            "revision_rate": round(sent[Performative.REVISE.value] / challenges, 3)
            if challenges
            else None,
        },
        "revisions": revisions,
        "conformity_flags": len(board.conformity_flags),
        "rejections": dict(Counter(item["code"] for item in board.rejections)),
        "verifier": {
            "vetoes": sum(report.decision == "VETO" for report in reports),
            "approvals": sum(report.decision == "APPROVE" for report in reports),
            "failed_gates": dict(
                Counter(g.gate for report in reports for g in report.gates if not g.passed)
            ),
            "under_call": any(report.under_call for report in reports),
        },
        "repairs": sum(event.type == "agent.repair" for event in events),
        "failures": dict(Counter(item["code"] for item in board.failures)),
        "rounds": [e.payload["phase"] for e in events if e.type == "round.started"],
        "spending": _spending(events),
    }


def trace_bundle(board: Blackboard, events: Sequence[Event]) -> dict[str, Any]:
    """A whole case in one object: masked, as stored."""
    return {
        "case_id": board.case_id,
        "state": board.snapshot(),
        "events": [event.model_dump(mode="json") for event in events],
        "telemetry": case_telemetry(board, events),
    }
