"""Identifiers and small enumerations shared across the protocol."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal


class AgentId(StrEnum):
    """Every actor that can write to the blackboard."""

    JUR = "JUR"  # Jurisdiction
    CMA = "CMA"  # CMA regulator agent
    DFSA = "DFSA"  # DFSA regulator agent
    VARA = "VARA"  # VARA regulator agent
    CLN = "CLN"  # Clone-check
    REC = "REC"  # Reconciler
    VER = "VER"  # Verifier
    ORC = "ORC"  # Orchestrator (deterministic)
    SA = "SA"  # Single-agent baseline


#: The agents that hold a regulator's rule card and register tools in Phase 1.
REGULATOR_AGENTS = (AgentId.CMA, AgentId.DFSA, AgentId.VARA)

Regulator = Literal["CMA", "DFSA", "VARA", "CBUAE", "FSRA"]
REGULATORS: tuple[Regulator, ...] = ("CMA", "DFSA", "VARA", "CBUAE", "FSRA")

RelevanceStatus = Literal["primary", "possible", "not_indicated", "excluded"]
Confidence = Literal["low", "medium", "high"]


class Zone(StrEnum):
    """Where an offer appears to operate from. Offer text gives claims, not facts."""

    DIFC = "DIFC"
    ADGM = "ADGM"
    DUBAI_NON_DIFC = "DUBAI_NON_DIFC"
    OTHER_EMIRATE = "OTHER_EMIRATE"
    OUTSIDE_UAE = "OUTSIDE_UAE"
    UNKNOWN = "UNKNOWN"


class ResultCode(StrEnum):
    """The three results. Display wording lives in ``policies/language_policy.yaml``."""

    CONSISTENT = "CONSISTENT"
    CONFLICTS = "CONFLICTS"
    UNVERIFIED = "UNVERIFIED"


def clip_words(text: str, limit: int = 60) -> str:
    """Shorten free text to ``limit`` words (message rationales are capped at 60)."""
    words = text.split()
    return text.strip() if len(words) <= limit else " ".join(words[:limit]) + " …"
