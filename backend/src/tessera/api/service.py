"""Runs cases in the background, and reads them back from the event log.

The event log is the only record of a case, so a live stream and a replay of a finished case are the
same thing: reading events in order. A case still has a report after a restart, because the board is
rebuilt from those events.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tessera.agents.base import AgentEnv
from tessera.agents.crew import CrewStack, covered_regulators
from tessera.blackboard.board import Blackboard
from tessera.blackboard.store import Event
from tessera.devdata import load_smoke_cases
from tessera.experiment import SAMPLE_MARK, open_condition, run_opened
from tessera.governance.synthetic_gate import Channel, OfferInput, pii_warnings
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import AgentId
from tessera.reporting.report import CaseReport, render_report
from tessera.reporting.telemetry import trace_bundle
from tessera.tools import ToolContext

logger = logging.getLogger(__name__)

#: The last event of a case. A stream ends here.
TERMINAL_EVENTS = frozenset({"result.finalized", "case.aborted"})


class CaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000)
    synthetic: bool
    corpus_item_id: str | None = None
    synthetic_attestation: bool = False
    channel: Channel | None = None
    condition: SystemCondition = SystemCondition.CREW_FULL


class UnknownCase(LookupError):
    pass


class CaseNotFinished(RuntimeError):
    pass


class ModelNotConfigured(RuntimeError):
    pass


class CaseService:
    def __init__(
        self,
        stack: CrewStack,
        *,
        model_ready: bool = True,
        not_ready_reason: str = "",
        today: date | None = None,
    ) -> None:
        self.stack = stack
        self.model_ready = model_ready
        self.not_ready_reason = not_ready_reason
        self.today = today
        self._running: dict[str, asyncio.Task[None]] = {}

    def start(self, request: CaseRequest) -> tuple[str, list[str]]:
        """Admit an offer and run it in the background. Returns its ID and any warnings."""
        if not self.model_ready:
            raise ModelNotConfigured(self.not_ready_reason)
        offer = OfferInput(
            text=request.text,
            synthetic=request.synthetic,
            corpus_item_id=request.corpus_item_id,
            synthetic_attestation=request.synthetic_attestation,
            channel=request.channel,
        )
        case_id = f"case-{uuid.uuid4().hex[:12]}"
        env = open_condition(self.stack, case_id, offer, condition=request.condition)
        task = asyncio.create_task(self._run(env, offer))
        self._running[case_id] = task
        task.add_done_callback(lambda _: self._running.pop(case_id, None))
        return case_id, [warning.message for warning in pii_warnings(offer.text)]

    async def _run(self, env: AgentEnv, offer: OfferInput) -> None:
        try:
            await run_opened(self.stack, env, offer, today=self.today or date.today())
        except Exception as exc:
            # Only the error's type is kept, because a message could quote a restricted value.
            logger.error("case %s stopped: %s", env.board.case_id, type(exc).__name__)
            env.board.record("case.aborted", AgentId.ORC, {"error": type(exc).__name__})

    async def wait(self) -> None:
        """Wait for every running case. Used on shutdown and in tests."""
        while self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)

    # ------------------------------------------------------------------ reading

    def events(self, case_id: str, *, after: int = 0) -> list[Event]:
        return self.stack.store.read(case_id, after=after)

    def is_running(self, case_id: str) -> bool:
        return case_id in self._running

    def exists(self, case_id: str) -> bool:
        return case_id in self.stack.store.case_ids()

    def board(self, case_id: str) -> Blackboard:
        if not self.exists(case_id):
            raise UnknownCase(case_id)
        return Blackboard.replay(self.stack.store, case_id, gateway=self.stack.gateway)

    def report(self, case_id: str) -> CaseReport:
        board = self.board(case_id)
        if board.final is None:
            raise CaseNotFinished(case_id)
        ctx = ToolContext.create(case_id, self.stack.settings, self.stack.registry)
        return render_report(board, ctx)

    def trace(self, case_id: str) -> dict[str, Any]:
        return trace_bundle(self.board(case_id), self.events(case_id))

    def cases(self) -> list[dict[str, Any]]:
        listed = []
        for case_id in self.stack.store.case_ids():
            if SAMPLE_MARK in case_id:
                continue
            board = self.board(case_id)
            listed.append(
                {
                    "case_id": case_id,
                    "condition": board.case.condition.value if board.case else None,
                    "result": board.final.result.value if board.final else None,
                    "running": case_id in self._running,
                }
            )
        return listed

    def status(self) -> dict[str, Any]:
        stack = self.stack
        ctx = ToolContext.create("status", stack.settings, stack.registry)
        sources = []
        for source_id, policy in ctx.sources.sources.items():
            if not policy.enabled or (policy.restricted and not stack.registry.restricted_allowed):
                continue
            manifest = stack.registry.table(source_id).manifest
            sources.append(
                {
                    "source_id": source_id,
                    "name": policy.name,
                    "regulator": policy.regulator,
                    "as_of": manifest.retrieved_on.isoformat() if manifest else None,
                    "rows": manifest.row_count if manifest else 0,
                }
            )
        return {
            "mode": stack.settings.mode.value,
            "model": stack.models.roles["primary"],
            "model_ready": self.model_ready,
            "not_ready_reason": self.not_ready_reason,
            "covered_regulators": sorted(covered_regulators(ctx.sources, stack.settings)),
            "conditions": [condition.value for condition in SystemCondition],
            "sources": sources,
        }

    def examples(self) -> list[dict[str, Any]]:
        """The fictional smoke offers, for trying the system. No gold field is included."""
        return [
            {"id": case.id, "channel": case.channel, "text": case.offer().text}
            for case in load_smoke_cases(self.stack.settings.root)
        ]
