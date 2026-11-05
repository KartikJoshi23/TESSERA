"""The resumable run harness (§13).

Each finished case is written to a file of its own, and a restart skips the files that exist. A run
can stop at any point, for a request budget, a time limit or a crash, and go on from there another
night. With about 8 requests a minute on the free tier, that is the only way a full run can work.

A record holds what a system did and said, and no gold label. Scoring joins the labels afterwards,
so a mistake here cannot show a system the answer. Records are built from masked events, so they
hold no DFSA value, and evaluation runs never use the replay cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tessera.agents.base import AgentEnv
from tessera.agents.crew import CrewStack
from tessera.blackboard.store import Event
from tessera.errors import GoldLabelLeak, RestrictedValueLeak
from tessera.evaluation.items import write_atomic
from tessera.evaluation.plan import Job
from tessera.experiment import SAMPLE_MARK, SC5_RUNS, model_for, models_for, run_opened
from tessera.governance.language import lint_text
from tessera.llm.config import ModelsPolicy
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import ResultCode
from tessera.protocol.results import FinalResult
from tessera.reporting.telemetry import case_telemetry

logger = logging.getLogger(__name__)

#: Stop rather than burn through a list while the provider is down.
MAX_FAILURES_IN_A_ROW = 3
#: A case the provider cut short says nothing about a system, so it runs again. A reply that broke
#: the rules, or a budget used up, is how the system behaved, so that one stands.
PROVIDER_FAILURES = frozenset({"model_error"})
_RELEVANT = frozenset({"primary", "possible"})


def _write_json(path: Path, value: dict[str, Any]) -> None:
    write_atomic(path, json.dumps(value, ensure_ascii=False, indent=1))


def record_path(run_dir: Path, job: Job) -> Path:
    return run_dir / "records" / job.condition.value / str(job.run) / f"{job.item.item_id}.json"


def failure_path(run_dir: Path, job: Job) -> Path:
    return run_dir / "failed" / job.condition.value / str(job.run) / f"{job.item.item_id}.json"


def build_record(
    job: Job,
    case_id: str,
    env: AgentEnv,
    final: FinalResult,
    events: Sequence[Event],
    seconds: float,
    *,
    failures: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """What a case produced. Everything here is read from the case itself."""
    board = env.board
    detail = final.detail
    cited = [evidence for claim in final.claims for evidence in claim.evidence_ids]
    said = " ".join((final.explanation, *(claim.text for claim in final.claims)))
    verdicts = {report.proposal_version: report.decision for report in board.verifier_reports}
    assert board.case is not None
    return {
        "item_id": job.item.item_id,
        "condition": job.condition.value,
        "run": job.run,
        "temperature": job.temperature,
        "case_id": case_id,
        "model": board.case.config["model"],
        "result": final.result.value,
        "hard_conflicts": list(final.hard_conflicts),
        "unverified_reasons": list(final.unverified_reasons),
        "policy_result": detail.get("policy_result"),
        "relevant": sorted(
            coverage.regulator for coverage in final.regulators if coverage.relevance in _RELEVANT
        ),
        "proposals": [
            {
                "version": proposal.version,
                "result": proposal.result.value,
                "verifier": verdicts.get(proposal.version),
            }
            for proposal in board.proposals
        ],
        "votes": detail.get("votes"),
        "requests": detail.get("requests", 0),
        "tokens": detail.get("prompt_tokens", 0) + detail.get("completion_tokens", 0),
        "seconds": round(seconds, 1),
        "cited": len(cited),
        "cited_valid": sum(evidence in board.evidence for evidence in cited),
        "banned_terms": len(lint_text(said, env.language)),
        "failures": [*(dict(failure) for failure in board.failures), *failures],
        "telemetry": case_telemetry(board, events),
    }


FINISHED = "finished"


@dataclass
class Progress:
    total: int
    done: int = 0
    skipped: int = 0
    failed: int = 0
    requests: int = 0
    failures_in_a_row: int = 0
    stopped_because: str = FINISHED


class Harness:
    def __init__(
        self,
        stack: CrewStack,
        run_dir: Path,
        *,
        today: date,
        clock: Callable[[], float] = time.monotonic,
        plan_hash: str = "",
    ) -> None:
        self.stack = stack
        self.run_dir = run_dir
        self.today = today
        self.clock = clock
        self.plan_hash = plan_hash

    def _models(self, job: Job) -> ModelsPolicy:
        models = models_for(self.stack.models, job.condition)
        if job.temperature is None:
            return models
        # Each stability run has its own seed, or all of them would be the same sample.
        seed = (models.decoding.seed or 0) + job.run
        return models.with_decoding(temperature=job.temperature, seed=seed)

    def _case_id(self, job: Job) -> str:
        """A fresh case each time, so a case a crash cut short is never appended to."""
        known = set(self.stack.store.case_ids())
        attempt = 0
        name = job.name
        while name in known:
            attempt += 1
            name = f"{job.name}~retry{attempt}"
        return name

    async def run_job(self, job: Job) -> dict[str, Any]:
        case_id = self._case_id(job)
        offer = job.item.offer()
        env = self.stack.open_case(
            case_id,
            offer,
            condition=job.condition,
            model=model_for(self.stack.models, job.condition),
            models=self._models(job),
        )
        started = self.clock()
        final = await run_opened(self.stack, env, offer, today=self.today)
        seconds = self.clock() - started
        events = self.stack.store.read(case_id)
        record = build_record(
            job, case_id, env, final, events, seconds, failures=self._sample_failures(job, case_id)
        )
        record["plan"] = self.plan_hash
        return record

    def _sample_failures(self, job: Job, case_id: str) -> list[dict[str, Any]]:
        """SA-SC5's samples are cases of their own, so their failures are not on its board."""
        if job.condition is not SystemCondition.SA_SC5:
            return []
        samples = (f"{case_id}{SAMPLE_MARK}{index + 1}" for index in range(SC5_RUNS))
        return [
            {"agent": event.actor, **event.payload}
            for sample in samples
            for event in self.stack.store.read(sample)
            if event.type == "agent.failed"
        ]

    def _save_progress(self, progress: Progress) -> None:
        _write_json(
            self.run_dir / "progress.json",
            {**progress.__dict__, "updated": datetime.now(UTC).isoformat(timespec="seconds")},
        )

    def _why_stop(self, progress: Progress, budget: int | None, deadline: float | None) -> str:
        """Why no new case should start now, or nothing if one can."""
        if progress.stopped_because != FINISHED:
            return progress.stopped_because
        if progress.failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
            return f"{progress.failures_in_a_row} failures in a row"
        if budget is not None and progress.requests >= budget:
            return "request budget"
        if deadline is not None and self.clock() >= deadline:
            return "time limit"
        return ""

    def _note_failure(
        self, job: Job, why: str, requests: int, progress: Progress, echo: Callable[[str], None]
    ) -> None:
        """No record, so the next session tries again. Until then the report counts it."""
        logger.error("%s stopped: %s", job.name, why)
        echo(f"{job.name}: stopped ({why})")
        progress.failed += 1
        progress.failures_in_a_row += 1
        progress.requests += requests
        _write_json(
            failure_path(self.run_dir, job),
            {
                "item_id": job.item.item_id,
                "condition": job.condition.value,
                "run": job.run,
                "result": ResultCode.UNVERIFIED.value,
                "gave_no_result": True,
                "failures": [{"code": why}],
                "requests": requests,
            },
        )

    async def _attempt(self, job: Job, progress: Progress, echo: Callable[[str], None]) -> None:
        try:
            record = await self.run_job(job)
        except (RestrictedValueLeak, GoldLabelLeak):
            # A guard stopped something leaving this machine. That ends the run, whatever else.
            raise
        except Exception as exc:
            self._note_failure(job, type(exc).__name__, 0, progress, echo)
        else:
            cut_short = {item.get("code") for item in record["failures"]} & PROVIDER_FAILURES
            if cut_short:
                self._note_failure(job, sorted(cut_short)[0], record["requests"], progress, echo)
            else:
                _write_json(record_path(self.run_dir, job), record)
                failure_path(self.run_dir, job).unlink(missing_ok=True)
                progress.failures_in_a_row = 0
                progress.done += 1
                progress.requests += record["requests"]
                echo(
                    f"{job.name}: {ResultCode(record['result']).value} "
                    f"({record['requests']} requests, {record['seconds']:.0f}s)"
                )
        self._save_progress(progress)

    async def run(
        self,
        jobs: Sequence[Job],
        *,
        max_requests: int | None = None,
        hours: float | None = None,
        parallel: int = 1,
        echo: Callable[[str], None] = lambda _: None,
    ) -> Progress:
        """Work through ``jobs``, skipping finished ones, until done or out of budget.

        The free tier limits requests, not cases, and a crew spends most of a case waiting for one
        reply at a time. ``parallel`` runs several cases at once under the one shared rate limiter,
        which fills the allowance without going over it. Each case keeps its own board.
        """
        if parallel < 1:
            raise ValueError("at least one case must run at a time")
        progress = Progress(total=len(jobs))
        deadline = self.clock() + hours * 3600 if hours else None
        waiting = iter(jobs)

        async def worker() -> None:
            for job in waiting:
                if record_path(self.run_dir, job).exists():
                    progress.skipped += 1
                    continue
                if reason := self._why_stop(progress, max_requests, deadline):
                    progress.stopped_because = reason
                    return
                await self._attempt(job, progress, echo)

        await asyncio.gather(*(worker() for _ in range(parallel)))
        self._save_progress(progress)
        return progress


def _read_all(root: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.rglob("*.json"))]


def load_records(run_dir: Path) -> list[dict[str, Any]]:
    """Every result, and every job that gave none. A system's crash must not flatter its score."""
    records = _read_all(run_dir / "records")
    answered = {(r["item_id"], r["condition"], r["run"]) for r in records}
    failed = _read_all(run_dir / "failed")
    return records + [r for r in failed if (r["item_id"], r["condition"], r["run"]) not in answered]
