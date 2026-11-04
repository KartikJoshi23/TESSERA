"""What the frontend relies on from the backend, recorded so that the two cannot drift apart.

``record_worked_case`` runs the worked example with scripted replies. Its events are fictional and
masked as stored, so they are safe to commit. Run this file to refresh the frontend's fixture:

    uv run python -m tests.frontend_contract
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from tessera.config.settings import Settings
from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.orchestration.graph import run_crew
from tessera.reporting.telemetry import trace_bundle

from .conftest import REPO_ROOT, CrewHarness, populate
from .scripted import Routed, worked_example

FIXTURE = REPO_ROOT / "frontend" / "src" / "lib" / "__fixtures__" / "worked-case.json"
REPLIES = 60


def record_worked_case(settings: Settings) -> dict[str, Any]:
    offer = next(case for case in load_smoke_cases(REPO_ROOT) if case.id == "S09").offer()
    script = Routed()
    setup = CrewHarness(settings, offer.text, *[script] * REPLIES, case_id="S09")
    script.queues = worked_example(setup)
    asyncio.run(run_crew(setup.env, today=FICTION_DATE))
    bundle = trace_bundle(setup.board, setup.store.read("S09"))
    return {"events": bundle["events"], "telemetry_requests": len(setup.transport.payloads)}


if __name__ == "__main__":
    recorded = record_worked_case(populate(Path(tempfile.mkdtemp()) / "data"))
    FIXTURE.write_text(json.dumps(recorded, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"recorded {len(recorded['events'])} events")
