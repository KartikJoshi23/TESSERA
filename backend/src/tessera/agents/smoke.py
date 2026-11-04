"""``tessera-smoke``: run the crew on the fictional smoke set, within a request cap.

Smoke runs use invented firms, in their own data folder under ``runs/``, and never touch real data.
This is a one-pass run with no challenge rounds; Part 3 adds those. A development replay cache
keeps repeated runs from using up free quota.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from tessera.agents.crew import build_crew, open_case_env, run_sequence
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode, load_settings
from tessera.data.registry import DataRegistry
from tessera.devdata import SmokeCase, install_world, load_smoke_cases
from tessera.errors import PolicyError
from tessera.governance.masking import MaskingGateway
from tessera.governance.policies import load_sources_policy
from tessera.llm.client import GuardedLLM
from tessera.llm.config import load_models_policy
from tessera.llm.stack import build_live_transport


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
    cache = None if args.no_cache else run_dir / "replay.sqlite"
    try:
        transport, http = build_live_transport(settings, models, cache_path=cache)
    except PolicyError as exc:
        print(f"tessera-smoke: {exc}", file=sys.stderr)
        return 2
    install_world(settings)
    sources = load_sources_policy(settings.policies_dir)
    registry = DataRegistry(settings, sources)
    gateway = MaskingGateway(registry.restricted_values())
    llm = GuardedLLM(transport, gateway)
    store = EventStore(run_dir / "events.sqlite")
    model = args.model or models.roles["primary"]
    cases = select_cases(load_smoke_cases(settings.root), args.cases, args.limit)
    total_requests = correct = 0
    print(f"model: {model}   cases: {len(cases)}   request cap: {args.max_requests}")
    print(f"{'case':<6}{'gold':<12}{'proposed':<12}{'veto':<6}{'requests':>9}{'tokens':>9}")
    try:
        for index, case in enumerate(cases, start=1):
            if total_requests >= args.max_requests:
                print(f"request cap reached after {index - 1} case(s)")
                break
            env = open_case_env(
                store=store,
                settings=settings,
                registry=registry,
                gateway=gateway,
                llm=llm,
                case_id=f"{case.id}-{store_size(store)}",
                offer=case.offer(),
                model=model,
                models=models,
            )
            turns = await run_sequence(env, build_crew())
            meter = env.runner.meter
            total_requests += meter.requests
            board = env.board
            proposed = board.proposals[-1].result.value if board.proposals else "-"
            veto = board.verifier_reports[-1].decision if board.verifier_reports else "-"
            correct += proposed == case.gold_label.value
            tokens = meter.prompt_tokens + meter.completion_tokens
            print(
                f"{case.id:<6}{case.gold_label.value:<12}{proposed:<12}{veto[:4]:<6}"
                f"{meter.requests:>9}{tokens:>9}"
            )
            for turn in turns:
                if turn.failure:
                    print(f"      {turn.agent_id.value} failed: {turn.failure}")
    finally:
        await http.aclose()
        store.close()
    print(f"\nmatches gold: {correct}/{len(cases)}   model requests: {total_requests}")
    print("These are fictional development cases. They say nothing about final performance.")
    return 0


def store_size(store: EventStore) -> int:
    return len(store.case_ids())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tessera-smoke", description="Run the crew on the fictional smoke set."
    )
    parser.add_argument("--cases", help="comma-separated case IDs, for example S01,S09")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    parser.add_argument("--max-requests", type=int, default=120, help="stop after this many")
    parser.add_argument("--model", help="model ID; default: the primary model")
    parser.add_argument("--run-dir", type=Path, help="default: runs/smoke")
    parser.add_argument("--no-cache", action="store_true", help="turn off the replay cache")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
