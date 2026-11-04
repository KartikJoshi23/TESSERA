"""The fictional world and smoke set in ``eval/smoke/``, for tests and smoke runs.

Every firm, domain and number in them is invented, so they are safe to commit. They are installed
through the same manual-ingest path as real data, which exercises that path too. Install them into
a separate data folder, never into ``data/``, so fictional and real records cannot mix.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field

from tessera.config.settings import Settings
from tessera.data.ingest import ingest_file
from tessera.data.schemas import SOURCE_SCHEMAS
from tessera.data.snapshots import SnapshotManifest, SnapshotStore
from tessera.governance.policies import load_sources_policy
from tessera.governance.synthetic_gate import OfferInput
from tessera.protocol.case import strip_gold
from tessera.protocol.common import ResultCode

FICTION_DATE = date(2026, 11, 4)
_RECORDED_BY = "FICTION"
_CMA_COLUMNS = {
    "name_en": "Company Name",
    "name_ar": "اسم الشركة",
    "licence_no": "License No",
    "category": "Category",
    "activities": "Activities",
    "status": "Status",
    "emirate": "Emirate",
    "website": "Website",
    "phone": "Phone",
    "email": "Email",
}


class SmokeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    channel: str
    text: str
    gold_label: ResultCode
    gold_reasons: tuple[str, ...] = ()
    gold_relevant: tuple[str, ...] = ()
    factors: tuple[str, ...] = Field(default=())

    def offer(self) -> OfferInput:
        """The offer as a system under test sees it. No gold field can reach it."""
        item = strip_gold(self.model_dump(mode="json"))
        return OfferInput(
            text=" ".join(item["text"].split()),
            synthetic=True,
            corpus_item_id=item["id"],
            channel=item["channel"],
        )


def _smoke_dir(root: Path) -> Path:
    return root / "eval" / "smoke"


def load_world(root: Path) -> dict[str, list[dict[str, Any]]]:
    text = (_smoke_dir(root) / "fictional_world.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_smoke_cases(root: Path) -> list[SmokeCase]:
    text = (_smoke_dir(root) / "cases.yaml").read_text(encoding="utf-8")
    return [SmokeCase(**item) for item in yaml.safe_load(text)["cases"]]


def _write_cma_workbook(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Licensed Companies (FICTIONAL TEST FIXTURE)"])
    sheet.append([])
    sheet.append(list(_CMA_COLUMNS.values()))
    for row in rows:
        sheet.append([row.get(column) for column in _CMA_COLUMNS])
    workbook.save(path)
    return path


def _write_csv(source_id: str, rows: list[dict[str, Any]], path: Path) -> Path:
    model = SOURCE_SCHEMAS[source_id]
    columns = [field.alias or name for name, field in model.model_fields.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {"recorded_by": _RECORDED_BY, "recorded_on": FICTION_DATE.isoformat(), **row}
            )
    return path


def install_world(settings: Settings) -> list[SnapshotManifest]:
    """Ingest the fictional world into ``settings.data_path``. Safe to call again."""
    if settings.data_path == (settings.root / "data").resolve():
        raise ValueError("install the fictional world into a separate data folder, never data/")
    world = load_world(settings.root)
    sources = load_sources_policy(settings.policies_dir)
    store = SnapshotStore(settings.data_path, restricted_allowed=settings.restricted_allowed)
    manifests: list[SnapshotManifest] = []
    for source_id, rows in world.items():
        restricted = sources.source(source_id).restricted
        if existing := store.latest(source_id, restricted=restricted):
            manifests.append(existing)
            continue
        base = settings.restricted_dir / "fiction" if restricted else settings.data_path / "inbox"
        if source_id == "cma_licensed":
            path = _write_cma_workbook(rows, base / f"{source_id}.xlsx")
        else:
            path = _write_csv(source_id, rows, base / f"{source_id}.csv")
        report = ingest_file(
            source_id,
            path,
            settings=settings,
            retrieved_by=_RECORDED_BY,
            retrieved_on=FICTION_DATE,
        )
        manifests.append(report.manifest)
    return manifests
