"""Every coordination mechanism is a switch, so each can be measured by turning it off (§10.2)."""

from __future__ import annotations

from dataclasses import dataclass

from tessera.blackboard.views import ViewOptions
from tessera.errors import PolicyError
from tessera.protocol.case import SystemCondition


@dataclass(frozen=True)
class CrewConfig:
    #: Agents see each other's findings.
    share: bool = True
    #: Agents can send requests and challenges, and the Reconciler mediates in rounds.
    challenges: bool = True
    #: The Verifier's gates, model checks and veto are on.
    verifier: bool = True
    max_challenge_rounds: int = 3
    max_remediations: int = 1

    @property
    def options(self) -> ViewOptions:
        return ViewOptions(share=self.share, messages=self.challenges)


CONDITIONS: dict[SystemCondition, CrewConfig] = {
    SystemCondition.CREW_FULL: CrewConfig(),
    SystemCondition.CREW_NV: CrewConfig(verifier=False),
    SystemCondition.CREW_SHARE: CrewConfig(challenges=False),
    SystemCondition.CREW_SILO: CrewConfig(share=False, challenges=False),
}


def config_for(condition: SystemCondition) -> CrewConfig:
    try:
        return CONDITIONS[condition]
    except KeyError:
        raise PolicyError(f"{condition} is not a crew condition") from None
