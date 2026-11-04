"""The message protocol: typed performatives modelled on FIPA-ACL speech acts (§6.4).

Agents never exchange raw model output. They exchange validated messages. The rules below are
enforced by the blackboard, not by prompts, so a model cannot talk its way around them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tessera.protocol.common import AgentId

RATIONALE_WORD_LIMIT = 60
Objection = Literal[
    "wrong_fact", "wrong_rule", "claim_not_fact", "missing_evidence", "scope", "other"
]


class Performative(StrEnum):
    INFORM = "INFORM"
    REQUEST = "REQUEST"
    CHALLENGE = "CHALLENGE"
    REBUT = "REBUT"
    REVISE = "REVISE"
    CONCEDE = "CONCEDE"
    RESOLVE = "RESOLVE"
    VETO = "VETO"
    APPROVE = "APPROVE"


#: Performatives that answer an earlier message.
REPLIES = frozenset({Performative.REBUT, Performative.REVISE, Performative.CONCEDE})


class MessageDraft(BaseModel):
    """What a sender proposes. The blackboard assigns the ID after checking the rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sender: AgentId
    recipients: tuple[AgentId, ...]
    performative: Performative
    round: int = 0
    refs: tuple[str, ...] = ()  # finding or conflict IDs this message is about
    evidence_ids: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    body: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    in_reply_to: str | None = None


class Message(MessageDraft):
    msg_id: str
    case_id: str


class ProtocolViolation(ValueError):
    """A message broke a protocol rule. ``code`` is a stable label used in telemetry."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
