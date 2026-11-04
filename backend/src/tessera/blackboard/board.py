"""The blackboard for one case (implementation-plan.md §6.2–§6.4).

Mutators never change state directly. Each one emits an event, and :meth:`Blackboard._apply` folds
that event into the state, so replaying the log rebuilds the same state (:meth:`Blackboard.replay`).

Two invariants are enforced here, at the single point where anything is persisted:

* **Masking.** Every event payload is checked for restricted values before it is written.
* **Protocol rules.** Messages are checked by :meth:`Blackboard.send`, not by prompts. A rejected
  message is logged, and a revision that cites nothing is logged as a conformity flag.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from tessera.blackboard.store import Event, EventStore
from tessera.config.settings import Mode
from tessera.errors import RestrictedValueLeak
from tessera.governance.masking import MaskingGateway
from tessera.governance.synthetic_gate import OfferInput, check_offer_input
from tessera.protocol.case import CaseRecord, SystemCondition
from tessera.protocol.claims import ASSERTION_ADAPTER, Assertion
from tessera.protocol.common import AgentId, Confidence
from tessera.protocol.conflicts import Conflict, ConflictStatus, ConflictType, Resolution
from tessera.protocol.contacts import ContactPoint
from tessera.protocol.evidence import EvidenceRecord
from tessera.protocol.findings import Finding, FindingStatus
from tessera.protocol.messages import (
    RATIONALE_WORD_LIMIT,
    REPLIES,
    Message,
    MessageDraft,
    Performative,
    ProtocolViolation,
)
from tessera.protocol.results import FinalResult, ProposedResult, VerifierReport
from tessera.tools.extract import extract_contact_points

_FINDING_PREFIX = {
    AgentId.JUR: "J",
    AgentId.CMA: "M",
    AgentId.DFSA: "D",
    AgentId.VARA: "V",
    AgentId.CLN: "C",
    AgentId.REC: "R",
    AgentId.VER: "X",
    AgentId.ORC: "O",
    AgentId.SA: "S",
}
_PRECEDENCE_RULES = frozenset(f"P{i}" for i in range(1, 8))


def _now() -> datetime:
    return datetime.now(UTC)


class Blackboard:
    def __init__(
        self,
        store: EventStore,
        case_id: str,
        *,
        gateway: MaskingGateway | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.store = store
        self.case_id = case_id
        self.gateway = gateway or MaskingGateway([])
        self._clock = clock
        self.case: CaseRecord | None = None
        self.evidence: dict[str, EvidenceRecord] = {}
        self.findings: dict[str, Finding] = {}
        self.history: dict[str, list[Finding]] = {}
        self.messages: list[Message] = []
        self.answered: set[str] = set()
        self.conflicts: dict[str, Conflict] = {}
        self.resolutions: dict[str, Resolution] = {}
        self.proposals: list[ProposedResult] = []
        self.verifier_reports: list[VerifierReport] = []
        self.final: FinalResult | None = None
        self.rejections: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self._counts: Counter[str] = Counter()

    # ------------------------------------------------------------------ opening and replay

    @classmethod
    def open_case(
        cls,
        store: EventStore,
        *,
        case_id: str,
        offer: OfferInput,
        condition: SystemCondition,
        mode: Mode,
        gateway: MaskingGateway | None = None,
        config: dict[str, Any] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> Blackboard:
        """Admit an offer through the synthetic gate, extract contacts, and record it masked."""
        warnings = check_offer_input(offer)
        board = cls(store, case_id, gateway=gateway, clock=clock)
        points = [board._masked_contact(point) for point in extract_contact_points(offer.text)]
        record = CaseRecord(
            case_id=case_id,
            condition=condition,
            mode=mode.value,
            offer_text=board.gateway.mask(offer.text),
            channel=offer.channel,
            corpus_item_id=offer.corpus_item_id,
            contact_points=tuple(points),
            pii_warning_kinds=tuple(sorted({w.kind for w in warnings})),
            config=config or {},
        )
        board._emit("case.created", AgentId.ORC, record.model_dump(mode="json"))
        return board

    @classmethod
    def replay(
        cls, store: EventStore, case_id: str, *, gateway: MaskingGateway | None = None
    ) -> Blackboard:
        """Rebuild a blackboard from its event log."""
        board = cls(store, case_id, gateway=gateway)
        for event in store.read(case_id):
            board._apply(event)
        return board

    def _masked_contact(self, point: ContactPoint) -> ContactPoint:
        return point.model_copy(
            update={
                "raw": self.gateway.mask(point.raw),
                "normalized": self.gateway.mask(point.normalized),
                "detail": self.gateway.mask_payload(point.detail),
            }
        )

    # ------------------------------------------------------------------ the single write path

    def _emit(
        self,
        kind: str,
        actor: AgentId | str,
        payload: dict[str, Any],
        *,
        usage: dict[str, int] | None = None,
        latency_ms: int | None = None,
    ) -> Event:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if self.gateway.leaked_values(text):
            # The values themselves are never logged, not even in this error.
            raise RestrictedValueLeak(f"a {kind} event held restricted values; nothing was written")
        event = Event(
            case_id=self.case_id,
            ts=self._clock(),
            actor=str(actor),
            type=kind,
            payload=payload,
            usage=usage,
            latency_ms=latency_ms,
        )
        stored = self.store.append(event)
        self._apply(stored)
        return stored

    def record(
        self,
        kind: str,
        actor: AgentId | str,
        payload: dict[str, Any] | None = None,
        *,
        usage: dict[str, int] | None = None,
        latency_ms: int | None = None,
    ) -> Event:
        """Log a telemetry event that does not change case state."""
        return self._emit(kind, actor, payload or {}, usage=usage, latency_ms=latency_ms)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}{self._counts[prefix] + 1}"

    def _apply(self, event: Event) -> None:
        handler = _APPLIERS.get(event.type)
        if handler is not None:
            handler(self, event)

    # ------------------------------------------------------------------ evidence

    def add_evidence(self, records: Iterable[EvidenceRecord]) -> None:
        """Store tool-minted evidence. Fields are masked, because a query can hold a real value."""
        for record in records:
            if record.evidence_id in self.evidence:
                continue
            masked = record.model_copy(
                update={
                    "fields": self.gateway.mask_payload(record.fields),
                    "locator": self.gateway.mask(record.locator),
                }
            )
            self._emit("evidence.minted", record.minted_by, masked.model_dump(mode="json"))

    def unknown_evidence(self, evidence_ids: Iterable[str]) -> tuple[str, ...]:
        """IDs that no tool created in this case. Agents cannot create evidence themselves."""
        return tuple(eid for eid in evidence_ids if eid not in self.evidence)

    # ------------------------------------------------------------------ findings

    def post_finding(
        self,
        author: AgentId,
        assertion: Assertion,
        *,
        evidence_ids: Sequence[str] = (),
        confidence: Confidence = "medium",
        depends_on: Sequence[str] = (),
        rationale: str = "",
        round: int = 0,
    ) -> Finding:
        """Post a finding. Unknown evidence IDs are kept and flagged (conflict type C6).

        Saying the same thing twice adds nothing, so it returns the finding already there. Models
        often repeat themselves when answering a message, and each repeat would look like news.
        """
        masked = ASSERTION_ADAPTER.validate_python(
            self.gateway.mask_payload(assertion.model_dump(mode="json"))
        )
        for existing in self.live_findings(masked.type):
            if existing.author is author and existing.assertion == masked:
                return existing
        prefix = f"F-{_FINDING_PREFIX[author]}"
        finding = Finding(
            finding_id=self._next_id(prefix),
            author=author,
            assertion=masked,
            confidence=confidence,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            depends_on=tuple(depends_on),
            rationale=self.gateway.mask(rationale),
            round=round,
            unknown_evidence_ids=self.unknown_evidence(dict.fromkeys(evidence_ids)),
        )
        self._emit("finding.posted", author, finding.model_dump(mode="json"))
        return self.findings[finding.finding_id]

    def live_findings(self, assertion_type: str | None = None) -> list[Finding]:
        found = [f for f in self.findings.values() if f.is_live]
        if assertion_type is not None:
            found = [f for f in found if f.assertion.type == assertion_type]
        return found

    def supersede_findings(self, author: AgentId, *, round: int = 0) -> None:
        """Replace everything an author said. A single agent answers a veto by starting again."""
        self._emit("findings.superseded", author, {"author": str(author), "round": round})

    def relevant_regulators(self) -> set[str]:
        """The union of relevance opinions (P5). Any agent's opinion can add a regulator."""
        return {
            f.assertion.regulator  # type: ignore[union-attr]
            for f in self.live_findings("relevance")
            if f.assertion.status in ("primary", "possible")  # type: ignore[union-attr]
        }

    def revise_finding(
        self,
        *,
        reply_to: str,
        sender: AgentId,
        assertion: Assertion,
        evidence_ids: Sequence[str] = (),
        rule_ids: Sequence[str] = (),
        rationale: str = "",
        round: int = 0,
    ) -> Finding:
        """Answer a challenge with a new version. The grounds for the change must be cited."""
        original = self.message(reply_to)
        target = self.findings.get(original.refs[0]) if original and original.refs else None
        if target is not None and assertion.type != target.assertion.type:
            self._reject("revision_changes_type", "a revision keeps the assertion type", sender)
        self.send(
            MessageDraft(
                sender=sender,
                recipients=(original.sender,) if original else (),
                performative=Performative.REVISE,
                round=round,
                refs=tuple(original.refs) if original else (),
                evidence_ids=tuple(evidence_ids),
                rule_ids=tuple(rule_ids),
                rationale=rationale,
                in_reply_to=reply_to,
            )
        )
        assert target is not None  # send() rejected the message otherwise
        merged = tuple(dict.fromkeys((*target.evidence_ids, *evidence_ids)))
        revised = target.model_copy(
            update={
                "version": target.version + 1,
                "assertion": ASSERTION_ADAPTER.validate_python(
                    self.gateway.mask_payload(assertion.model_dump(mode="json"))
                ),
                "evidence_ids": merged,
                "status": FindingStatus.ACTIVE,
                "rationale": self.gateway.mask(rationale),
                "round": round,
                "unknown_evidence_ids": self.unknown_evidence(merged),
            }
        )
        self._emit("finding.revised", sender, revised.model_dump(mode="json"))
        return self.findings[target.finding_id]

    # ------------------------------------------------------------------ messages

    def message(self, msg_id: str | None) -> Message | None:
        return next((m for m in self.messages if m.msg_id == msg_id), None)

    def inbox(self, agent: AgentId) -> list[Message]:
        """Requests, challenges and vetoes addressed to ``agent`` that are still unanswered."""
        waiting = (Performative.REQUEST, Performative.CHALLENGE, Performative.VETO)
        return [
            m
            for m in self.messages
            if agent in m.recipients and m.performative in waiting and m.msg_id not in self.answered
        ]

    def log_rejection(self, code: str, detail: str, sender: AgentId) -> None:
        """Record that something an agent proposed broke a rule. Counted in telemetry."""
        self._emit(
            "protocol.rejected",
            sender,
            {"code": code, "detail": self.gateway.mask(detail), "sender": str(sender)},
        )

    def _reject(self, code: str, detail: str, sender: AgentId) -> None:
        self.log_rejection(code, detail, sender)
        raise ProtocolViolation(code, detail)

    def _check(self, draft: MessageDraft) -> None:
        kind, sender = draft.performative, draft.sender
        if len(draft.rationale.split()) > RATIONALE_WORD_LIMIT:
            self._reject("rationale_too_long", f"more than {RATIONALE_WORD_LIMIT} words", sender)
        if kind is Performative.INFORM:
            if not draft.refs and draft.in_reply_to is None:
                self._reject("inform_without_content", "INFORM names no finding", sender)
            if draft.in_reply_to is not None:
                original = self.message(draft.in_reply_to)
                if (
                    original is None
                    or sender not in original.recipients
                    or original.performative is not Performative.REQUEST
                ):
                    self._reject("bad_reply", "an INFORM reply answers a REQUEST", sender)
        elif kind is Performative.REQUEST:
            if len(draft.recipients) != 1 or not draft.body.get("question"):
                self._reject("bad_request", "a REQUEST has one recipient and a question", sender)
        elif kind is Performative.CHALLENGE:
            self._check_challenge(draft)
        elif kind in REPLIES:
            self._check_reply(draft)
        elif kind is Performative.RESOLVE:
            self._check_resolve(draft)
        elif kind in (Performative.VETO, Performative.APPROVE) and sender is not AgentId.VER:
            self._reject("verifier_only", f"only the Verifier may send {kind}", sender)

    def _check_challenge(self, draft: MessageDraft) -> None:
        sender = draft.sender
        if len(draft.refs) != 1:
            self._reject("bad_challenge", "a CHALLENGE targets exactly one finding", sender)
        target = self.findings.get(draft.refs[0])
        if target is None or not target.is_live:
            self._reject("unknown_target", f"no live finding {draft.refs[0]}", sender)
        assert target is not None
        if draft.recipients != (target.author,):
            self._reject("wrong_recipient", "a CHALLENGE goes to the finding's author", sender)
        if target.author is sender:
            self._reject("self_challenge", "an agent cannot challenge itself", sender)
        if not (draft.evidence_ids or draft.rule_ids):
            self._reject("challenge_without_grounds", "cite counter-evidence or a rule", sender)
        if not draft.body.get("question"):
            self._reject("bad_challenge", "a CHALLENGE asks a question", sender)

    def _check_reply(self, draft: MessageDraft) -> None:
        sender = draft.sender
        original = self.message(draft.in_reply_to)
        if original is None or sender not in original.recipients:
            self._reject("bad_reply", "a reply must answer a message sent to its sender", sender)
        assert original is not None
        if original.performative is not Performative.CHALLENGE:
            self._reject("bad_reply", f"{draft.performative} answers a CHALLENGE", sender)
        if draft.performative is Performative.CONCEDE:
            return
        if not (draft.evidence_ids or draft.rule_ids):
            code = (
                "revision_without_citation"
                if draft.performative is Performative.REVISE
                else "rebuttal_without_citation"
            )
            self._reject(code, "cite the evidence or rule behind this position", sender)

    def _check_resolve(self, draft: MessageDraft) -> None:
        sender = draft.sender
        if sender is not AgentId.REC:
            self._reject("reconciler_only", "only the Reconciler may RESOLVE", sender)
        if len(draft.refs) != 1 or draft.refs[0] not in self.conflicts:
            self._reject("unknown_conflict", "RESOLVE names one known conflict", sender)
        if draft.body.get("precedence_rule") not in _PRECEDENCE_RULES:
            self._reject("no_precedence_rule", "every resolution cites a rule P1–P7", sender)

    def send(self, draft: MessageDraft) -> Message:
        """Check a message against the protocol rules, then record it."""
        self._check(draft)
        message = Message(
            **self.gateway.mask_payload(draft.model_dump(mode="json")),
            msg_id=self._next_id("M-"),
            case_id=self.case_id,
        )
        self._emit("message.sent", draft.sender, message.model_dump(mode="json"))
        return self.messages[-1]

    def try_send(self, draft: MessageDraft) -> Message | None:
        """:meth:`send`, for model-proposed messages: a rejection is logged, not fatal."""
        try:
            return self.send(draft)
        except ProtocolViolation:
            return None

    @property
    def conformity_flags(self) -> list[dict[str, Any]]:
        """Revisions rejected for citing nothing: an agent agreeing without grounds."""
        return [r for r in self.rejections if r["code"] == "revision_without_citation"]

    # ------------------------------------------------------------------ conflicts

    def add_conflict(
        self,
        conflict_type: ConflictType,
        finding_ids: Sequence[str],
        *,
        detected_by: str = "detector",
        summary: str = "",
    ) -> Conflict:
        conflict = Conflict(
            conflict_id=self._next_id("CF-"),
            type=conflict_type,
            finding_ids=tuple(finding_ids),
            detected_by=detected_by,  # type: ignore[arg-type]
            summary=self.gateway.mask(summary),
        )
        self._emit("conflict.detected", AgentId.ORC, conflict.model_dump(mode="json"))
        return self.conflicts[conflict.conflict_id]

    def open_conflicts(self) -> list[Conflict]:
        return [
            c
            for c in self.conflicts.values()
            if c.status in (ConflictStatus.OPEN, ConflictStatus.CHALLENGED)
        ]

    def settle_conflict(self, conflict_id: str, *, round: int = 0) -> None:
        """Close a conflict whose trigger no longer holds. Only the detector does this."""
        self._emit("conflict.settled", AgentId.ORC, {"conflict_id": conflict_id, "round": round})

    def resolve_conflict(
        self,
        conflict_id: str,
        *,
        outcome: str,
        precedence_rule: str,
        winning_finding_ids: Sequence[str] = (),
        evidence_ids: Sequence[str] = (),
        rationale: str = "",
        round: int = 0,
    ) -> Resolution:
        """Record a resolution. A RESOLVE message carries the check on the precedence rule."""
        self.send(
            MessageDraft(
                sender=AgentId.REC,
                recipients=(AgentId.ORC,),
                performative=Performative.RESOLVE,
                round=round,
                refs=(conflict_id,),
                evidence_ids=tuple(evidence_ids),
                body={"outcome": outcome, "precedence_rule": precedence_rule},
                rationale=rationale,
            )
        )
        resolution = Resolution(
            resolution_id=self._next_id("RS-"),
            conflict_id=conflict_id,
            outcome=outcome,  # type: ignore[arg-type]
            winning_finding_ids=tuple(winning_finding_ids),
            precedence_rule=precedence_rule,
            evidence_ids=tuple(evidence_ids),
            rationale=self.gateway.mask(rationale),
            round=round,
        )
        self._emit("conflict.resolved", AgentId.REC, resolution.model_dump(mode="json"))
        return self.resolutions[resolution.resolution_id]

    # ------------------------------------------------------------------ results

    def post_proposal(self, proposal: ProposedResult) -> ProposedResult:
        masked = ProposedResult.model_validate(
            self.gateway.mask_payload(proposal.model_dump(mode="json"))
        )
        self._emit("proposal.created", proposal.author, masked.model_dump(mode="json"))
        return self.proposals[-1]

    def post_verifier_report(self, report: VerifierReport) -> VerifierReport:
        masked = VerifierReport.model_validate(
            self.gateway.mask_payload(report.model_dump(mode="json"))
        )
        self._emit("verifier.decision", AgentId.VER, masked.model_dump(mode="json"))
        return self.verifier_reports[-1]

    def finalize(self, result: FinalResult) -> FinalResult:
        masked = FinalResult.model_validate(
            self.gateway.mask_payload(result.model_dump(mode="json"))
        )
        self._emit("result.finalized", AgentId.ORC, masked.model_dump(mode="json"))
        assert self.final is not None
        return self.final

    def note_failure(self, agent: AgentId, code: str, detail: str = "") -> None:
        """An agent could not finish. The case will resolve as reason U7."""
        self._emit("agent.failed", agent, {"code": code, "detail": self.gateway.mask(detail)[:300]})

    # ------------------------------------------------------------------ inspection

    def snapshot(self) -> dict[str, Any]:
        """The full case state as plain JSON. Replay must reproduce it exactly."""

        def dump(items: Iterable[Any]) -> list[Any]:
            return [item.model_dump(mode="json") for item in items]

        return {
            "case": self.case.model_dump(mode="json") if self.case else None,
            "evidence": dump(self.evidence.values()),
            "findings": dump(self.findings.values()),
            "history": {k: dump(v) for k, v in self.history.items()},
            "messages": dump(self.messages),
            "answered": sorted(self.answered),
            "conflicts": dump(self.conflicts.values()),
            "resolutions": dump(self.resolutions.values()),
            "proposals": dump(self.proposals),
            "verifier_reports": dump(self.verifier_reports),
            "final": self.final.model_dump(mode="json") if self.final else None,
            "rejections": self.rejections,
            "failures": self.failures,
        }


# ---------------------------------------------------------------------- event folding


def _on_case(board: Blackboard, event: Event) -> None:
    board.case = CaseRecord.model_validate(event.payload)


def _on_evidence(board: Blackboard, event: Event) -> None:
    record = EvidenceRecord.model_validate(event.payload)
    board.evidence[record.evidence_id] = record


def _bump(board: Blackboard, identifier: str) -> None:
    """Advance the counter behind IDs such as ``F-J3``, so replay assigns the same IDs."""
    prefix = identifier.rstrip("0123456789")
    board._counts[prefix] = max(board._counts[prefix], int(identifier[len(prefix) :]))


def _on_finding(board: Blackboard, event: Event) -> None:
    finding = Finding.model_validate(event.payload)
    _bump(board, finding.finding_id)
    board.findings[finding.finding_id] = finding
    board.history[finding.finding_id] = [finding]


def _on_revision(board: Blackboard, event: Event) -> None:
    finding = Finding.model_validate(event.payload)
    previous = board.history[finding.finding_id]
    previous[-1] = previous[-1].model_copy(update={"status": FindingStatus.SUPERSEDED})
    previous.append(finding)
    board.findings[finding.finding_id] = finding


def _set_status(board: Blackboard, finding_id: str, status: FindingStatus) -> None:
    finding = board.findings.get(finding_id)
    if finding is None:
        return
    updated = finding.model_copy(update={"status": status})
    board.findings[finding_id] = updated
    board.history[finding_id][-1] = updated


def _on_message(board: Blackboard, event: Event) -> None:
    message = Message.model_validate(event.payload)
    _bump(board, message.msg_id)
    board.messages.append(message)
    if message.in_reply_to:
        board.answered.add(message.in_reply_to)
    if message.performative is Performative.CHALLENGE:
        _set_status(board, message.refs[0], FindingStatus.CHALLENGED)
    elif message.performative is Performative.CONCEDE:
        _set_status(board, message.refs[0], FindingStatus.WITHDRAWN)


def _on_conflict(board: Blackboard, event: Event) -> None:
    conflict = Conflict.model_validate(event.payload)
    _bump(board, conflict.conflict_id)
    board.conflicts[conflict.conflict_id] = conflict


def _on_resolution(board: Blackboard, event: Event) -> None:
    resolution = Resolution.model_validate(event.payload)
    _bump(board, resolution.resolution_id)
    board.resolutions[resolution.resolution_id] = resolution
    status = (
        ConflictStatus.UNRESOLVED if resolution.outcome == "unresolved" else ConflictStatus.RESOLVED
    )
    conflict = board.conflicts[resolution.conflict_id]
    board.conflicts[resolution.conflict_id] = conflict.model_copy(
        update={"status": status, "resolution_id": resolution.resolution_id}
    )


def _on_settled(board: Blackboard, event: Event) -> None:
    conflict_id = event.payload["conflict_id"]
    board.conflicts[conflict_id] = board.conflicts[conflict_id].model_copy(
        update={"status": ConflictStatus.SETTLED}
    )


def _on_superseded(board: Blackboard, event: Event) -> None:
    for finding in list(board.findings.values()):
        if finding.author.value == event.payload["author"] and finding.is_live:
            _set_status(board, finding.finding_id, FindingStatus.SUPERSEDED)


def _on_proposal(board: Blackboard, event: Event) -> None:
    board.proposals.append(ProposedResult.model_validate(event.payload))


def _on_verifier(board: Blackboard, event: Event) -> None:
    board.verifier_reports.append(VerifierReport.model_validate(event.payload))


def _on_final(board: Blackboard, event: Event) -> None:
    board.final = FinalResult.model_validate(event.payload)


def _on_rejected(board: Blackboard, event: Event) -> None:
    board.rejections.append(event.payload)


def _on_failed(board: Blackboard, event: Event) -> None:
    board.failures.append({"agent": event.actor, **event.payload})


_APPLIERS: dict[str, Callable[[Blackboard, Event], None]] = {
    "case.created": _on_case,
    "evidence.minted": _on_evidence,
    "finding.posted": _on_finding,
    "finding.revised": _on_revision,
    "findings.superseded": _on_superseded,
    "message.sent": _on_message,
    "conflict.detected": _on_conflict,
    "conflict.resolved": _on_resolution,
    "conflict.settled": _on_settled,
    "proposal.created": _on_proposal,
    "verifier.decision": _on_verifier,
    "result.finalized": _on_final,
    "protocol.rejected": _on_rejected,
    "agent.failed": _on_failed,
}
