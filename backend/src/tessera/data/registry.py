"""Read-only access to the latest snapshot of each source, respecting the operating mode.

Tables are small, so lookups scan them in memory. Nothing here builds a search index, which also
keeps the DFSA rule against "retrieval systems" simple to honour.
"""

from __future__ import annotations

from dataclasses import dataclass

from tessera.config.settings import Settings
from tessera.data.schemas import SOURCE_SCHEMAS, BaseRecord
from tessera.data.snapshots import SnapshotManifest, SnapshotStore
from tessera.errors import RestrictedDataUnavailable
from tessera.governance.masking import RestrictedValue
from tessera.governance.policies import SourcesPolicy


@dataclass(frozen=True)
class FactTable:
    source_id: str
    manifest: SnapshotManifest | None
    records: tuple[BaseRecord, ...]
    restricted: bool

    @property
    def available(self) -> bool:
        return self.manifest is not None

    def get(self, record_id: str) -> BaseRecord | None:
        return next((r for r in self.records if r.record_id == record_id), None)


class DataRegistry:
    def __init__(
        self, settings: Settings, sources: SourcesPolicy, store: SnapshotStore | None = None
    ) -> None:
        self.settings = settings
        self.sources = sources
        self.store = store or SnapshotStore(
            settings.data_path, restricted_allowed=settings.restricted_allowed
        )
        self._tables: dict[str, FactTable] = {}

    @property
    def restricted_allowed(self) -> bool:
        return self.settings.restricted_allowed

    def table(self, source_id: str) -> FactTable:
        """The latest snapshot of ``source_id``; an empty table if none was ingested yet."""
        if source_id in self._tables:
            return self._tables[source_id]
        policy = self.sources.source(source_id)
        if policy.restricted and not self.restricted_allowed:
            raise RestrictedDataUnavailable(
                f"{source_id} is restricted; it loads only in RESEARCH_INTERNAL mode"
            )
        manifest = self.store.latest(source_id, restricted=policy.restricted)
        model = SOURCE_SCHEMAS[source_id]
        records = tuple(self.store.load(manifest, model)) if manifest else ()
        table = FactTable(source_id, manifest, records, policy.restricted)
        self._tables[source_id] = table
        return table

    def restricted_values(self) -> list[RestrictedValue]:
        """Every restricted value currently loaded, for the masking gateway."""
        if not self.restricted_allowed:
            return []
        values: list[RestrictedValue] = []
        for source_id, policy in self.sources.sources.items():
            if policy.restricted and policy.enabled and source_id in SOURCE_SCHEMAS:
                for record in self.table(source_id).records:
                    values.extend(record.restricted_values())
        return values
