"""Readers for manually obtained files: the CMA Excel export and hand-record CSVs.

The CMA export's exact columns are confirmed only at the first real export, so headers are
matched by known English and Arabic aliases. If detection fails, an explicit column map can be
used instead (see ``data/handrecords/templates/cma_column_map.example.yaml``).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, TypeVar

import yaml
from openpyxl import load_workbook
from pydantic import ValidationError

from tessera.data.schemas import BaseRecord, CmaLicensedRecord
from tessera.errors import IngestError
from tessera.normalize.names import normalize_text

R = TypeVar("R", bound=BaseRecord)

_CMA_ALIASES_RAW: dict[str, tuple[str, ...]] = {
    "name_en": (
        "company name",
        "company name english",
        "company name en",
        "name english",
        "english name",
        "name",
        "company",
        "entity name",
        "licensed company",
        "licensed entity",
    ),
    "name_ar": (
        "company name arabic",
        "company name ar",
        "name arabic",
        "arabic name",
        "اسم الشركة",
        "الاسم",
        "اسم الجهة",
    ),
    "licence_no": (
        "license no",
        "licence no",
        "license number",
        "licence number",
        "license",
        "licence",
        "رقم الترخيص",
    ),
    "category": (
        "category",
        "license category",
        "licence category",
        "license type",
        "licence type",
        "الفئة",
        "فئة الترخيص",
    ),
    "activities": (
        "activity",
        "activities",
        "licensed activity",
        "licensed activities",
        "license activities",
        "النشاط",
        "الأنشطة",
    ),
    "status": ("status", "license status", "licence status", "الحالة"),
    "emirate": ("emirate", "city", "location", "الإمارة"),
    "website": ("website", "web site", "url", "web", "الموقع الإلكتروني", "الموقع"),
    "phone": ("phone", "telephone", "tel", "phone number", "الهاتف"),
    "email": ("email", "e mail", "البريد الإلكتروني"),
}
CMA_HEADER_ALIASES: dict[str, frozenset[str]] = {
    field: frozenset(normalize_text(alias) for alias in aliases)
    for field, aliases in _CMA_ALIASES_RAW.items()
}
_HEADER_SEARCH_ROWS = 20


def load_column_map(path: Path) -> dict[str, str]:
    """Read an explicit ``field: header text`` mapping for the CMA export."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IngestError(f"cannot read column map {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise IngestError(f"{path.name} must map field names to header text")
    unknown = set(data) - set(CMA_HEADER_ALIASES)
    if unknown:
        raise IngestError(f"{path.name}: unknown fields {sorted(unknown)}")
    return {str(k): str(v) for k, v in data.items()}


def _cell_text(row: tuple[Any, ...], index: int) -> str | None:
    if index >= len(row) or row[index] is None:
        return None
    value = row[index]
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _header_map(cells: tuple[Any, ...], column_map: dict[str, str] | None) -> dict[str, int]:
    if column_map:
        wanted = {
            field: frozenset({normalize_text(header)}) for field, header in column_map.items()
        }
    else:
        wanted = dict(CMA_HEADER_ALIASES)
    mapping: dict[str, int] = {}
    for index, cell in enumerate(cells):
        if cell is None:
            continue
        header = normalize_text(str(cell))
        for field, options in wanted.items():
            if field not in mapping and header in options:
                mapping[field] = index
                break
    return mapping


def read_cma_excel(
    path: Path, column_map: dict[str, str] | None = None
) -> tuple[list[CmaLicensedRecord], list[str]]:
    """Read the CMA "Export To Excel" file. Returns records and non-fatal warnings."""
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several unrelated types for bad files
        raise IngestError(f"cannot open {path.name} as an Excel workbook: {exc}") from exc
    try:
        rows = [tuple(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]
    finally:
        workbook.close()

    header_index, mapping = None, {}
    for index, row in enumerate(rows[:_HEADER_SEARCH_ROWS]):
        candidate = _header_map(row, column_map)
        if ("name_en" in candidate or "name_ar" in candidate) and len(candidate) >= 2:
            header_index, mapping = index, candidate
            break
    if header_index is None:
        raise IngestError(
            f"{path.name}: no header row with a company-name column found in the first "
            f"{_HEADER_SEARCH_ROWS} rows; supply --column-map"
        )

    headers = [str(c).strip() if c is not None else "" for c in rows[header_index]]
    records: list[CmaLicensedRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if all(c is None or str(c).strip() == "" for c in row):
            continue
        values = {field: _cell_text(row, column) for field, column in mapping.items()}
        if not (values.get("name_en") or values.get("name_ar")):
            warnings.append(f"row {row_number}: no company name; skipped")
            continue
        raw = {h: t for i, h in enumerate(headers) if h and (t := _cell_text(row, i)) is not None}
        base_id = values.get("licence_no") or f"ROW{row_number:05d}"
        record_id, suffix = base_id, 2
        while record_id in seen:
            record_id, suffix = f"{base_id}-{suffix}", suffix + 1
        seen.add(record_id)
        try:
            records.append(CmaLicensedRecord(record_id=record_id, raw=raw, **values))
        except ValidationError as exc:
            raise IngestError(f"{path.name}, row {row_number}: {exc.errors()[0]['msg']}") from exc
    return records, warnings


def read_handrecord_csv(path: Path, model: type[R]) -> list[R]:
    """Read a hand-record CSV made from a template; every row is validated."""
    columns = {f.alias or name for name, f in model.model_fields.items()}
    required = {f.alias or name for name, f in model.model_fields.items() if f.is_required()}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise IngestError(f"{path.name} is empty")
        headers = {h.strip() for h in reader.fieldnames if h}
        if unknown := headers - columns:
            raise IngestError(f"{path.name}: unknown columns {sorted(unknown)}; use the template")
        if missing := required - headers:
            raise IngestError(f"{path.name}: missing columns {sorted(missing)}; use the template")
        records: list[R] = []
        errors: list[str] = []
        seen: set[str] = set()
        for line, row in enumerate(reader, start=2):
            data = {k.strip(): v for k, v in row.items() if k}
            if all(not (v or "").strip() for v in data.values()):
                continue
            try:
                record = model(**data)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
                )
                errors.append(f"line {line}: {details}")
                continue
            if record.record_id in seen:
                errors.append(f"line {line}: duplicate record_id {record.record_id}")
                continue
            seen.add(record.record_id)
            records.append(record)
    if errors:
        shown = "\n  ".join(errors[:20])
        raise IngestError(f"{path.name}: {len(errors)} invalid row(s):\n  {shown}")
    return records
