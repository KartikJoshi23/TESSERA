"""The context every tool receives: case ID, settings, policies and the data registry."""

from __future__ import annotations

from dataclasses import dataclass

from tessera.config.settings import Settings, load_settings
from tessera.data.registry import DataRegistry
from tessera.governance.links import sanitize_link
from tessera.governance.policies import (
    DecisionPolicy,
    SourcesPolicy,
    load_decision_policy,
    load_sources_policy,
)
from tessera.knowledge import ActivityTaxonomy, load_activity_taxonomy


@dataclass
class ToolContext:
    case_id: str
    settings: Settings
    sources: SourcesPolicy
    decision: DecisionPolicy
    registry: DataRegistry
    taxonomy: ActivityTaxonomy

    @classmethod
    def create(
        cls, case_id: str, settings: Settings | None = None, registry: DataRegistry | None = None
    ) -> ToolContext:
        settings = settings or load_settings()
        sources = load_sources_policy(settings.policies_dir)
        return cls(
            case_id=case_id,
            settings=settings,
            sources=sources,
            decision=load_decision_policy(settings.policies_dir),
            registry=registry or DataRegistry(settings, sources),
            taxonomy=load_activity_taxonomy(settings.knowledge_dir),
        )

    def link(self, source_id: str, url: str | None = None) -> str:
        """A policy-compliant evidence link (DFSA: homepage only)."""
        return sanitize_link(source_id, url, self.sources)
