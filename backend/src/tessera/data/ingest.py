"""``tessera-ingest``: register a manually obtained file as an immutable snapshot.

The command never touches the network. It does four things:

1. reads one local file that a person obtained by hand;
2. validates it against the source's schema;
3. records provenance (who, when, the file's hash);
4. writes an immutable snapshot.

DFSA files are accepted only from ``data/restricted/`` and only in ``RESEARCH_INTERNAL`` mode.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from tessera.config.settings import Settings, load_settings
from tessera.data.adapters import load_column_map, read_cma_excel, read_handrecord_csv
from tessera.data.schemas import SOURCE_SCHEMAS, BaseRecord
from tessera.data.snapshots import SnapshotManifest, SnapshotStore, file_sha256, make_snapshot_id
from tessera.errors import IngestError, RestrictedDataUnavailable, TesseraError
from tessera.governance.network import install_network_guard
from tessera.governance.policies import load_sources_policy


@dataclass
class IngestReport:
    manifest: SnapshotManifest
    path: Path
    warnings: list[str] = field(default_factory=list)


def ingest_file(
    source_id: str,
    file_path: Path,
    *,
    settings: Settings,
    retrieved_by: str,
    retrieved_on: date,
    source_url: str | None = None,
    page_last_modified: date | None = None,
    notes: str | None = None,
    column_map: Path | None = None,
    now: datetime | None = None,
) -> IngestReport:
    """Validate one manual file and store it as a new snapshot."""
    policy = load_sources_policy(settings.policies_dir).source(source_id)
    if source_id not in SOURCE_SCHEMAS:
        raise IngestError(f"no schema is defined for {source_id!r}")
    if not policy.enabled:
        raise IngestError(f"{source_id} is not enabled yet (phase {policy.phase})")
    if not retrieved_by.strip():
        raise IngestError("--retrieved-by (your initials) is required")
    file_path = file_path.resolve()
    if not file_path.is_file():
        raise IngestError(f"file not found: {file_path}")

    if policy.restricted:
        if not settings.restricted_allowed:
            raise RestrictedDataUnavailable(
                f"{source_id} is restricted: set TESSERA_MODE=RESEARCH_INTERNAL to ingest it"
            )
        if not file_path.is_relative_to(settings.restricted_dir.resolve()):
            raise IngestError(f"{source_id} files must be stored under {settings.restricted_dir}")
        if source_url not in (None, policy.homepage):
            raise IngestError(f"{source_id}: only the homepage {policy.homepage} may be recorded")
        source_url = policy.homepage

    warnings: list[str] = []
    records: list[BaseRecord]
    if source_id == "cma_licensed":
        if file_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise IngestError("the CMA file must be the .xlsx from the 'Export To Excel' button")
        mapping = load_column_map(column_map) if column_map else None
        cma_records, warnings = read_cma_excel(file_path, mapping)
        records = list(cma_records)
    else:
        if file_path.suffix.lower() != ".csv":
            raise IngestError(f"{source_id} expects a CSV file made from its template")
        records = list(read_handrecord_csv(file_path, SOURCE_SCHEMAS[source_id]))
    if not records:
        raise IngestError(f"{file_path.name} contains no records")

    sha256 = file_sha256(file_path)
    manifest = SnapshotManifest(
        snapshot_id=make_snapshot_id(source_id, retrieved_on, sha256),
        source_id=source_id,
        retrieved_on=retrieved_on,
        retrieved_by=retrieved_by.strip(),
        source_url=source_url or policy.page_url,
        page_last_modified=page_last_modified,
        input_file=file_path.name,
        input_sha256=sha256,
        row_count=len(records),
        restricted=policy.restricted,
        created_at=now or datetime.now(UTC),
        notes=notes,
    )
    store = SnapshotStore(settings.data_path, restricted_allowed=settings.restricted_allowed)
    return IngestReport(manifest, store.write(manifest, records), warnings)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tessera-ingest",
        description="Register a manually obtained file as an immutable snapshot (no network).",
    )
    parser.add_argument("source_id", help="for example cma_licensed, vara_register, dfsa_alerts")
    parser.add_argument("file", type=Path, help="the file you downloaded or filled in by hand")
    parser.add_argument("--retrieved-by", required=True, help="your initials")
    parser.add_argument("--retrieved-on", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--source-url", help="the page the file came from (not for DFSA)")
    parser.add_argument("--page-last-modified", type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--notes")
    parser.add_argument("--column-map", type=Path, help="CMA only: explicit header mapping")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        settings = load_settings()
        install_network_guard(
            load_sources_policy(settings.policies_dir).network.deny_automated_domains
        )
        report = ingest_file(
            args.source_id,
            args.file,
            settings=settings,
            retrieved_by=args.retrieved_by,
            retrieved_on=args.retrieved_on,
            source_url=args.source_url,
            page_last_modified=args.page_last_modified,
            notes=args.notes,
            column_map=args.column_map,
        )
    except TesseraError as exc:
        print(f"tessera-ingest: {exc}", file=sys.stderr)
        return 2
    manifest = report.manifest
    kind = "restricted snapshot" if manifest.restricted else "snapshot"
    print(f"Created {kind} {manifest.snapshot_id}: {manifest.row_count} record(s).")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
