"""Proposed results, Verifier reports and final results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tessera.protocol.claims import Assertion
from tessera.protocol.common import AgentId, Regulator, RelevanceStatus, ResultCode


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResultClaim(_Frozen):
    """One claim behind a result: a typed assertion, the sentence it renders to, its evidence."""

    finding_id: str
    assertion: Assertion
    text: str
    evidence_ids: tuple[str, ...] = ()


class RegulatorCoverage(_Frozen):
    regulator: Regulator
    relevance: RelevanceStatus
    checked: bool
    rationale: str = ""


class ProposedResult(_Frozen):
    version: int
    author: AgentId
    result: ResultCode
    hard_conflicts: tuple[str, ...] = ()
    unverified_reasons: tuple[str, ...] = ()
    claims: tuple[ResultClaim, ...] = ()
    regulators: tuple[RegulatorCoverage, ...] = ()
    explanation: str = ""
    round: int = 0


class GateResult(_Frozen):
    gate: str
    passed: bool
    detail: str = ""


class EntailmentCheck(_Frozen):
    claim_index: int
    verdict: Literal["supported", "partly_supported", "unsupported"]
    rationale: str = ""


class ContradictionCheck(_Frozen):
    evidence_id: str
    claim_index: int | None = None
    rationale: str = ""


class VerifierReport(_Frozen):
    proposal_version: int
    decision: Literal["APPROVE", "VETO"]
    gates: tuple[GateResult, ...] = ()
    entailment: tuple[EntailmentCheck, ...] = ()
    contradictions: tuple[ContradictionCheck, ...] = ()
    veto_reasons: tuple[str, ...] = ()
    under_call: bool = False


class FinalResult(_Frozen):
    """The result after the Verifier. ``wording`` is the exact display string."""

    result: ResultCode
    wording: str
    explanation: str
    proposal_version: int | None = None
    hard_conflicts: tuple[str, ...] = ()
    unverified_reasons: tuple[str, ...] = ()
    claims: tuple[ResultClaim, ...] = ()
    regulators: tuple[RegulatorCoverage, ...] = ()
    disclaimer: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
