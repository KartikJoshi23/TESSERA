"""The Conflict Detector: deterministic rules C1–C7 (§6.6).

It runs after every round. A trigger that holds opens a conflict once. A conflict whose trigger no
longer holds, for example because a challenged agent revised its finding, is settled without any
model request. The Reconciler can open conflicts these rules miss, and those are measured
separately, so conflicts it opened are never settled here.
"""

from __future__ import annotations

# A finding's assertion is a union. Each rule picks findings by type first, so attributes are safe.
# mypy: disable-error-code="union-attr"
from dataclasses import dataclass

from tessera.agents.base import AgentEnv
from tessera.orchestration.decision import DecisionEngine
from tessera.protocol.common import REGULATORS, AgentId
from tessera.protocol.conflicts import Conflict, ConflictStatus, ConflictType
from tessera.protocol.findings import Finding

_RELEVANT = frozenset({"primary", "possible"})
_REGULATOR_AUTHORS = {"CMA": AgentId.CMA, "DFSA": AgentId.DFSA, "VARA": AgentId.VARA}
_ADVERSE_CONTACT = frozenset({"alert_listed", "lookalike_of_official"})


@dataclass(frozen=True)
class Trigger:
    type: ConflictType
    finding_ids: tuple[str, ...]
    summary: str

    @property
    def key(self) -> tuple[ConflictType, frozenset[str]]:
        return self.type, frozenset(self.finding_ids)


def _key(conflict: Conflict) -> tuple[ConflictType, frozenset[str]]:
    return conflict.type, frozenset(conflict.finding_ids)


class _Rules:
    def __init__(self, env: AgentEnv, engine: DecisionEngine) -> None:
        self.env = env
        self.engine = engine
        self.board = env.board
        self.live = env.board.live_findings()

    def of(self, kind: str) -> list[Finding]:
        return [f for f in self.live if f.assertion.type == kind]

    def _entity(self, finding: Finding) -> str | None:
        record = self.board.evidence.get(finding.assertion.entity_evidence_id)
        return f"{record.source_id}:{record.locator}" if record else None

    def relevance(self) -> list[Trigger]:
        """C1. Primary and possible both mean "relevant", so only that split counts."""
        found: list[Trigger] = []
        for regulator in REGULATORS:
            author = _REGULATOR_AUTHORS.get(regulator)
            opinions = [f for f in self.of("relevance") if f.assertion.regulator == regulator]
            jurisdiction = [f for f in opinions if f.author is AgentId.JUR]
            own = [f for f in opinions if f.author is author]
            for first in jurisdiction:
                for second in own:
                    if (first.assertion.status in _RELEVANT) != (
                        second.assertion.status in _RELEVANT
                    ):
                        found.append(
                            Trigger(
                                ConflictType.C1,
                                (first.finding_id, second.finding_id),
                                f"Jurisdiction and {regulator} disagree on relevance.",
                            )
                        )
        return found

    def identity(self) -> list[Trigger]:
        """C2: several entries for one claimed firm, or a reference number of another firm."""
        matches = self.of("register_match")
        found: list[Trigger] = []
        if len({self._entity(m) for m in matches}) > 1:
            ids = tuple(m.finding_id for m in matches)
            found.append(Trigger(ConflictType.C2, ids, "Several register entries match."))
        found += [
            Trigger(
                ConflictType.C2,
                (m.finding_id,),
                "The claimed reference number belongs to a firm with another name.",
            )
            for m in matches
            if m.finding_id not in self.engine.invalid and self.engine._reference_mismatch(m)
        ]
        return found

    def scope(self) -> list[Trigger]:
        """C3: an activity outside the licence of a firm that another finding treats as licensed."""
        found: list[Trigger] = []
        for scope in self.of("licence_scope"):
            if scope.assertion.covered != "no":
                continue
            for status in self.of("licence_status"):
                if self._entity(status) == self._entity(scope) and status.assertion.status in (
                    "active",
                    "ipa",
                ):
                    found.append(
                        Trigger(
                            ConflictType.C3,
                            (scope.finding_id, status.finding_id),
                            f"{scope.assertion.activity} is outside a licence on the register.",
                        )
                    )
        return found

    def contact(self) -> list[Trigger]:
        """C4: Clone-check and a regulator agent disagree about a contact point."""
        found: list[Trigger] = []
        contacts = self.of("contact_assessment")
        listed = [a for a in self.of("alert_hit") if a.assertion.about == "contact_listed"]
        for contact in contacts:
            if contact.assertion.status == "matches_official":
                found += [
                    Trigger(
                        ConflictType.C4,
                        (contact.finding_id, alert.finding_id),
                        "A contact point assessed as official is named on a list.",
                    )
                    for alert in listed
                ]
            elif contact.assertion.status in _ADVERSE_CONTACT:
                found += [
                    Trigger(
                        ConflictType.C4,
                        (contact.finding_id, match.finding_id),
                        "A match confirmed by a contact detail conflicts with the contact check.",
                    )
                    for match in self.of("register_match")
                    if match.assertion.second_identifier
                    and "reference" not in match.assertion.second_identifier
                ]
        return found

    def alert_against_register(self) -> list[Trigger]:
        """C5: a firm on a register is also named in an impersonation alert."""
        return [
            Trigger(
                ConflictType.C5,
                (match.finding_id, alert.finding_id),
                "A registered firm is named in an impersonation alert.",
            )
            for match in self.of("register_match")
            for alert in self.of("alert_hit")
            if alert.assertion.about == "impersonation_of_entity"
        ]

    def missing_evidence(self) -> list[Trigger]:
        """C6: a finding cites nothing, or evidence that does not say what it claims."""
        return [
            Trigger(ConflictType.C6, (f.finding_id,), problems[0])
            for f in self.live
            if (problems := self.engine.checker.problems(f))
        ]

    def claim_against_record(self) -> list[Trigger]:
        """C7: the offer claims one regulator, and the firm is on another's register."""
        found: list[Trigger] = []
        for claim, code in self.engine.claimed_regulators():
            absent = [n for n in self.of("register_no_match") if n.assertion.regulator == code]
            matches = self.of("register_match")
            here = [m for m in matches if m.assertion.regulator == code]
            elsewhere = [m for m in matches if m.assertion.regulator != code]
            if code is not None and absent and not here and elsewhere:
                found.append(
                    Trigger(
                        ConflictType.C7,
                        (claim.finding_id, absent[0].finding_id, elsewhere[0].finding_id),
                        f"The offer claims {code}, but the firm is on another register.",
                    )
                )
        return found


def find_triggers(env: AgentEnv, engine: DecisionEngine) -> list[Trigger]:
    rules = _Rules(env, engine)
    return [
        *rules.relevance(),
        *rules.identity(),
        *rules.scope(),
        *rules.contact(),
        *rules.alert_against_register(),
        *rules.missing_evidence(),
        *rules.claim_against_record(),
    ]


def run_detector(env: AgentEnv, engine: DecisionEngine, *, round: int = 0) -> list[Conflict]:
    """Open conflicts for new triggers and settle those whose trigger has gone."""
    board = env.board
    triggers = {trigger.key: trigger for trigger in find_triggers(env, engine)}
    for conflict in board.open_conflicts():
        if conflict.detected_by == "detector" and _key(conflict) not in triggers:
            board.settle_conflict(conflict.conflict_id, round=round)
    known = {_key(c) for c in board.conflicts.values() if c.status is not ConflictStatus.SETTLED}
    return [
        board.add_conflict(trigger.type, trigger.finding_ids, summary=trigger.summary)
        for key, trigger in triggers.items()
        if key not in known
    ]
