"""``tessera-smoke``: run the crew on the fictional smoke set, within a request cap.

Smoke runs use invented firms, in their own data folder under ``runs/``, and never touch real data.
A development replay cache keeps repeated runs from using up free quota.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from tessera.agents.crew import build_crew, build_stack
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode, load_settings
from tessera.devdata import FICTION_DATE, SmokeCase, install_world, load_smoke_cases
from tessera.errors import PolicyError
from tessera.llm.config import load_models_policy
from tessera.llm.stack import build_live_transport
from tessera.orchestration.graph import run_crew
from tessera.protocol.case import SystemCondition


def select_cases(cases: list[SmokeCase], wanted: str | None, limit: int | None) -> list[SmokeCase]:
    if wanted:
        ids = {item.strip() for item in wanted.split(",") if item.strip()}
        cases = [case for case in cases if case.id in ids]
    return cases[:limit] if limit else cases


async def _run(args: argparse.Namespace) -> int:
    root = load_settings().root
    run_dir = (args.run_dir or root / "runs" / "smoke").resolve()
    settings = load_settings(mode=Mode.RESEARCH_INTERNAL, data_dir=run_dir / "data")
    models = load_models_policy(settings.policies_dir)
    if args.thinking:
        models = models.with_thinking(args.thinking == "on")
    cache = None if args.no_cache else run_dir / "replay.sqlite"
    try:
        transport, http = build_live_transport(settings, models, cache_path=cache)
    except PolicyError as exc:
        print(f"tessera-smoke: {exc}", file=sys.stderr)
        return 2
    install_world(settings)
    store = EventStore(run_dir / "events" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.sqlite")
    stack = build_stack(settings, transport, store, models)
    model = args.model or models.roles["primary"]
    condition = SystemCondition(args.condition)
    cases = select_cases(load_smoke_cases(settings.root), args.cases, args.limit)
    total_requests = correct = 0
    print(
        f"model: {model}   condition: {condition.value}   cases: {len(cases)}   "
        f"request cap: {args.max_requests}"
    )
    print(
        f"{'case':<6}{'gold':<12}{'result':<12}{'requests':>9}{'tokens':>9}{'sec':>6}  reasons",
        flush=True,
    )
    try:
        for index, case in enumerate(cases, start=1):
            if total_requests >= args.max_requests:
                print(f"request cap reached after {index - 1} case(s)")
                break
            # Evidence IDs include the case ID, so a stable ID lets a repeat run use the cache.
            env = stack.open_case(case.id, case.offer(), condition=condition, model=model)
            started = time.monotonic()
            final = await run_crew(env, crew=build_crew(), today=FICTION_DATE)
            seconds = time.monotonic() - started
            meter = env.runner.meter
            total_requests += meter.requests
            correct += final.result is case.gold_label
            tokens = meter.prompt_tokens + meter.completion_tokens
            reasons = ",".join((*final.hard_conflicts, *final.unverified_reasons))
            print(
                f"{case.id:<6}{case.gold_label.value:<12}{final.result.value:<12}"
                f"{meter.requests:>9}{tokens:>9}{seconds:>6.0f}  {reasons}",
                flush=True,
            )
            for failure in env.board.failures:
                print(f"      {failure['agent']} failed: {failure['code']}", flush=True)
    finally:
        await http.aclose()
        store.close()
    print(f"\nmatches gold: {correct}/{len(cases)}   model requests: {total_requests}")
    print("These are fictional development cases. They say nothing about final performance.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tessera-smoke", description="Run the crew on the fictional smoke set."
    )
    parser.add_argument("--cases", help="comma-separated case IDs, for example S01,S09")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    parser.add_argument("--max-requests", type=int, default=120, help="stop after this many")
    parser.add_argument("--model", help="model ID; default: the primary model")
    parser.add_argument(
        "--condition",
        default=SystemCondition.CREW_FULL.value,
        choices=[c.value for c in SystemCondition if c.value.startswith("CREW")],
    )
    parser.add_argument(
        "--thinking", choices=["on", "off"], help="override the primary model's reasoning setting"
    )
    parser.add_argument("--run-dir", type=Path, help="default: runs/smoke")
    parser.add_argument("--no-cache", action="store_true", help="turn off the replay cache")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
