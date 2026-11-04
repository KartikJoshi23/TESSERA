"""The HTTP API (§3). It has no sign-in because it serves this machine only (§9.4, item 7).

:func:`main` always binds to 127.0.0.1, and there is no option to change that. Requests must also
name a local host, which stops a web page in a browser from reaching the API through a domain that
it points at this machine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sse_starlette.sse import EventSourceResponse

from tessera.agents.crew import build_stack
from tessera.api.service import (
    TERMINAL_EVENTS,
    CaseNotFinished,
    CaseRequest,
    CaseService,
    ModelNotConfigured,
    UnknownCase,
)
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode, Settings, load_settings
from tessera.devdata import FICTION_DATE, install_world
from tessera.errors import PolicyError, SyntheticInputRejected
from tessera.llm.config import load_models_policy
from tessera.llm.stack import build_live_transport
from tessera.llm.types import PermanentLLMError

LOCAL_HOSTS = ["127.0.0.1", "localhost"]
#: The Next.js development server (Part 5).
LOCAL_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
DEFAULT_PORT = 8000
_POLL_SECONDS = 0.2


def create_app(service: CaseService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await service.wait()

    app = FastAPI(
        title="TESSERA", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    app.add_middleware(
        CORSMiddleware, allow_origins=LOCAL_ORIGINS, allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return service.status()

    @app.get("/api/examples")
    def examples() -> list[dict[str, Any]]:
        return service.examples()

    @app.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        return service.cases()

    @app.post("/api/cases", status_code=202)
    async def start_case(request: CaseRequest) -> dict[str, Any]:
        try:
            case_id, warnings = service.start(request)
        except SyntheticInputRejected as exc:
            raise HTTPException(422, str(exc)) from exc
        except ModelNotConfigured as exc:
            raise HTTPException(503, str(exc)) from exc
        except PolicyError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "case_id": case_id,
            "warnings": warnings,
            "events": f"/api/cases/{case_id}/events",
            "report": f"/api/cases/{case_id}/report",
        }

    @app.get("/api/cases/{case_id}")
    def case_state(case_id: str) -> dict[str, Any]:
        try:
            return service.board(case_id).snapshot()
        except UnknownCase as exc:
            raise HTTPException(404, f"no case {case_id}") from exc

    @app.get("/api/cases/{case_id}/trace")
    def case_trace(case_id: str) -> dict[str, Any]:
        """The whole case, with its coordination telemetry. Masked, as stored."""
        try:
            return service.trace(case_id)
        except UnknownCase as exc:
            raise HTTPException(404, f"no case {case_id}") from exc

    @app.get("/api/cases/{case_id}/report")
    def case_report(case_id: str) -> dict[str, Any]:
        try:
            return service.report(case_id).model_dump(mode="json")
        except UnknownCase as exc:
            raise HTTPException(404, f"no case {case_id}") from exc
        except CaseNotFinished as exc:
            raise HTTPException(409, "the case has not finished") from exc

    @app.get("/api/cases/{case_id}/events")
    async def case_events(case_id: str, request: Request, after: int = 0) -> EventSourceResponse:
        """Every event of a case in order, live or replayed. Masked, as stored."""
        if not service.exists(case_id):
            raise HTTPException(404, f"no case {case_id}")
        resume = request.headers.get("last-event-id", "")
        start = int(resume) if resume.isdecimal() else after

        async def stream() -> AsyncIterator[dict[str, str]]:
            position = start
            while True:
                for event in service.events(case_id, after=position):
                    position = event.seq or position
                    yield {
                        "id": str(event.seq),
                        "event": event.type,
                        "data": json.dumps(
                            event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                        ),
                    }
                    if event.type in TERMINAL_EVENTS:
                        return
                # Nothing is running this case, for example after a restart, so nothing else
                # will arrive. The second read catches a case that ended since the first.
                if not service.is_running(case_id) and not service.events(case_id, after=position):
                    yield {"event": "case.interrupted", "data": json.dumps({"case_id": case_id})}
                    return
                await asyncio.sleep(_POLL_SECONDS)

        return EventSourceResponse(stream())

    return app


class _NoModel:
    """Stands in for the transport when no key is set. The service never reaches it."""

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise PermanentLLMError("no model is configured")


def _not_ready_stack(settings: Settings, reason: str) -> CaseService:
    """Without a key, finished cases can still be read. Starting one reports the reason."""
    models = load_models_policy(settings.policies_dir)
    store = EventStore(settings.root / "runs" / "api" / "events.sqlite")
    stack = build_stack(settings, _NoModel(), store, models)
    return CaseService(stack, model_ready=False, not_ready_reason=reason)


def build_service(*, fiction: bool = False) -> CaseService:
    """The live service. ``fiction`` uses the fictional world, in its own folder."""
    root = load_settings().root
    settings = (
        load_settings(mode=Mode.RESEARCH_INTERNAL, data_dir=(root / "runs" / "api" / "data"))
        if fiction
        else load_settings()
    )
    today: date | None = None
    if fiction:
        install_world(settings)
        today = FICTION_DATE
    models = load_models_policy(settings.policies_dir)
    try:
        transport, _ = build_live_transport(settings, models)
    except PolicyError as exc:
        return _not_ready_stack(settings, str(exc))
    store = EventStore(settings.root / "runs" / "api" / "events.sqlite")
    return CaseService(build_stack(settings, transport, store, models), today=today)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tessera-api", description="Run the local API.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--fiction", action="store_true", help="use the fictional world, not the data/ folder"
    )
    args = parser.parse_args(argv)
    uvicorn.run(create_app(build_service(fiction=args.fiction)), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
