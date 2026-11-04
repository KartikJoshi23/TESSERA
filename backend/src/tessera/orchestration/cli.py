"""``tessera-run``: run one offer through the crew and print its report.

``--case S09`` runs a fictional smoke case against the fictional world, and needs no real data.
``--text`` runs your own synthetic text against the data in ``data/``, and you must attest that it
is synthetic. Real messages are never allowed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path

from tessera.agents.crew import build_stack
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode, Settings, load_settings
from tessera.devdata import FICTION_DATE, install_world, load_smoke_cases
from tessera.errors import PolicyError, SyntheticInputRejected
from tessera.governance.synthetic_gate import OfferInput
from tessera.llm.config import load_models_policy
from tessera.llm.stack import build_live_transport
from tessera.orchestration.graph import run_crew
from tessera.protocol.case import SystemCondition
from tessera.reporting.report import CaseReport, render_report


def print_report(report: CaseReport, *, usage: dict[str, object]) -> None:
    print(f"\n{report.wording.upper()}   [SYNTHETIC · {report.case_id} · {report.condition}]\n")
    print(report.explanation)
    for rule in (*report.hard_conflicts, *report.unverified_reasons):
        print(f"  {rule.id}: {rule.text}")
    if report.claims:
        print("\nClaims")
    for claim in report.claims:
        print(f"  - {claim.text}")
        for chip in claim.evidence:
            dates = " ".join(
                part
                for part in (
                    f"as of {chip.as_of}" if chip.as_of else "",
                    f"dated {chip.dated}" if chip.dated else "",
                )
                if part
            )
            print(f"      {chip.source} ({chip.kind}) {dates}".rstrip())
    if report.regulators:
        print("\nRegulators")
    for coverage in report.regulators:
        state = "checked" if coverage.checked else "not checked in this phase"
        print(f"  {coverage.regulator}: {coverage.relevance}, {state}")
    if report.sources:
        print("\nRecords as of")
    for source in report.sources:
        print(f"  {source.source}: {source.as_of}")
    if report.how_to_verify:
        print("\nTo confirm directly")
    for link in report.how_to_verify:
        print(f"  {link.regulator}: {link.link}")
    print(f"\n{report.disclaimer}\n")
    print(f"policy: {usage['policy_result']}   requests: {usage['requests']}")


def _offer_and_settings(args: argparse.Namespace) -> tuple[OfferInput, Settings, date]:
    if args.case:
        root = load_settings().root
        settings = load_settings(
            mode=Mode.RESEARCH_INTERNAL, data_dir=(root / "runs" / "smoke" / "data").resolve()
        )
        install_world(settings)
        cases = {case.id: case for case in load_smoke_cases(settings.root)}
        if args.case not in cases:
            raise PolicyError(f"no smoke case {args.case}")
        return cases[args.case].offer(), settings, FICTION_DATE
    offer = OfferInput(text=args.text, synthetic=True, synthetic_attestation=args.attest_synthetic)
    return offer, load_settings(), date.today()


async def _run(args: argparse.Namespace) -> int:
    try:
        offer, settings, today = _offer_and_settings(args)
        models = load_models_policy(settings.policies_dir)
        transport, http = build_live_transport(settings, models)
    except PolicyError as exc:
        print(f"tessera-run: {exc}", file=sys.stderr)
        return 2
    store = EventStore((args.run_dir or settings.root / "runs" / "cases") / "events.sqlite")
    stack = build_stack(settings, transport, store, models)
    case_id = f"{args.case or 'text'}-{uuid.uuid4().hex[:8]}"
    try:
        env = stack.open_case(
            case_id, offer, condition=SystemCondition(args.condition), model=args.model
        )
        final = await run_crew(env, today=today)
        print_report(render_report(env.board, env.ctx), usage=final.detail)
    except SyntheticInputRejected as exc:
        print(f"tessera-run: {exc}", file=sys.stderr)
        return 2
    finally:
        await http.aclose()
        store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tessera-run", description="Run one synthetic offer through the crew."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", help="a fictional smoke case, for example S09")
    source.add_argument("--text", help="your own synthetic offer text")
    parser.add_argument(
        "--attest-synthetic",
        action="store_true",
        help="with --text: I confirm this text is synthetic, not a real message",
    )
    parser.add_argument(
        "--condition",
        default=SystemCondition.CREW_FULL.value,
        choices=[c.value for c in SystemCondition if c.value.startswith("CREW")],
    )
    parser.add_argument("--model", help="model ID; default: the primary model")
    parser.add_argument("--run-dir", type=Path, help="default: runs/cases")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
