"""Immutable, versioned snapshots of manually obtained sources, with provenance manifests.

Layout (all under the git-ignored data folder)::

    data/snapshots/<source_id>/<snapshot_id>/{records.jsonl, manifest.json}
    data/restricted/snapshots/<source_id>/<snapshot_id>/…      (restricted sources)

A snapshot is never overwritten. Restricted snapshots can be written or read only when the store
was opened with ``restricted_allowed=True`` (``RESEARCH_INTERNAL`` mode).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from tessera.data.schemas import BaseRecord
from tessera.errors import IngestError, RestrictedDataUnavailable

R = TypeVar("R", bound=BaseRecord)
SCHEMA_VERSION = 1


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    source_id: str
    schema_version: int = SCHEMA_VERSION
    retrieved_on: date
    retrieved_by: str
    source_url: str | None = None
    page_last_modified: date | None = None
    input_file: str
    input_sha256: str
    row_count: int
    restricted: bool
    created_at: datetime
    notes: str | None = None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_snapshot_id(source_id: str, retrieved_on: date, sha256: str) -> str:
    return f"{source_id}-{retrieved_on:%Y%m%d}-{sha256[:8]}"


class SnapshotStore:
    def __init__(self, data_dir: Path, *, restricted_allowed: bool) -> None:
        self.data_dir = data_dir
        self.restricted_allowed = restricted_allowed

    def _base(self, restricted: bool) -> Path:
        return (
            self.data_dir / "restricted" / "snapshots"
            if restricted
            else self.data_dir / "snapshots"
        )

    def _guard(self, restricted: bool) -> None:
        if restricted and not self.restricted_allowed:
            raise RestrictedDataUnavailable(
                "restricted snapshots are available only in RESEARCH_INTERNAL mode"
            )

    def path_for(self, manifest: SnapshotManifest) -> Path:
        return self._base(manifest.restricted) / manifest.source_id / manifest.snapshot_id

    def write(self, manifest: SnapshotManifest, records: list[BaseRecord]) -> Path:
        self._guard(manifest.restricted)
        target = self.path_for(manifest)
        if target.exists():
            raise IngestError(
                f"snapshot {manifest.snapshot_id} already exists; snapshots are immutable"
            )
        staging = target.with_name(target.name + ".tmp")
        if staging.exists():
            shutil.rmtree(staging)  # left over from an interrupted run
        staging.mkdir(parents=True)
        with (staging / "records.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                row = record.model_dump(mode="json", by_alias=True)
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        (staging / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(target)
        return target

    def manifests(self, source_id: str, *, restricted: bool) -> list[SnapshotManifest]:
        """All snapshots of a source, oldest first."""
        self._guard(restricted)
        base = self._base(restricted) / source_id
        if not base.is_dir():
            return []
        found = []
        for folder in base.iterdir():
            manifest_file = folder / "manifest.json"
            if folder.is_dir() and not folder.name.endswith(".tmp") and manifest_file.is_file():
                found.append(SnapshotManifest.model_validate_json(manifest_file.read_text("utf-8")))
        return sorted(found, key=lambda m: (m.retrieved_on, m.created_at, m.snapshot_id))

    def latest(self, source_id: str, *, restricted: bool) -> SnapshotManifest | None:
        snapshots = self.manifests(source_id, restricted=restricted)
        return snapshots[-1] if snapshots else None

    def load(self, manifest: SnapshotManifest, model: type[R]) -> list[R]:
        self._guard(manifest.restricted)
        lines = (self.path_for(manifest) / "records.jsonl").read_text("utf-8").splitlines()
        return [model.model_validate_json(line) for line in lines if line.strip()]
