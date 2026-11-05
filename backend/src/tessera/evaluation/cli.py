"""``tessera-eval``: build datasets, run the plan, and report it.

``--fiction`` works on the fictional world, under ``runs/eval/``. That is for dry runs of the whole
pipeline before any real record is loaded. Its numbers say how the machinery behaves, and they are
not evaluation results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from tessera.agents.crew import CrewStack, build_stack
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode, load_settings
from tessera.devdata import FICTION_DATE, install_world
from tessera.errors import PolicyError
from tessera.evaluation.entities import build_entity_items
from tessera.evaluation.firms import load_world
from tessera.evaluation.harness import Harness, load_records
from tessera.evaluation.items import EvalItem, Split, content_hash, read_items, write_items
from tessera.evaluation.leakage import scan
from tessera.evaluation.messages import build_message_items
from tessera.evaluation.metrics import summarize
from tessera.evaluation.plan import jobs_for, load_plan, plan_hash
from tessera.evaluation.report import evaluation_report, outcomes_by_condition, render_text
from tessera.evaluation.review import compare_labels, export_sheet, read_sheet
from tessera.evaluation.scenarios import sample_scenarios
from tessera.evaluation.splits import assign_splits, of_split
from tessera.evaluation.statistics import mcnemar_power
from tessera.evaluation.writing import writing_brief
from tessera.knowledge import load_activity_taxonomy
from tessera.llm.config import load_models_policy
from tessera.llm.stack import build_live_transport
from tessera.llm.types import PermanentLLMError
from tessera.protocol.case import SystemCondition

DEFAULT_SEED = 20261105
#: RULES-ONLY above this on the development split means the messages are too formulaic (§11.2 D).
DIFFICULTY_LIMIT = 0.7


class _NoModel:
    """For work that needs no model. Reaching this is a bug, and it says so."""

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise PermanentLLMError("this command does not call a model")


def _stack(args: argparse.Namespace, *, model: bool, log: Path) -> tuple[CrewStack, date, Any]:
    root = load_settings().root
    settings = (
        load_settings(mode=Mode.RESEARCH_INTERNAL, data_dir=root / "runs" / "eval" / "data")
        if args.fiction
        else load_settings(mode=Mode.RESEARCH_INTERNAL)
    )
    today = (
        FICTION_DATE
        if args.fiction
        else (date.fromisoformat(args.today) if args.today else date.today())
    )
    if args.fiction:
        install_world(settings)
    models = load_models_policy(settings.policies_dir)
    if args.thinking:
        models = models.with_thinking(args.thinking == "on")
    transport: Any = _NoModel()
    http = None
    if model:
        transport, http = build_live_transport(settings, models)
    return build_stack(settings, transport, EventStore(log), models), today, http


def _scratch_log() -> Path:
    return Path(tempfile.mkdtemp(prefix="tessera-eval-")) / "events.sqlite"


def _world(stack: CrewStack) -> Any:
    taxonomy = load_activity_taxonomy(stack.settings.knowledge_dir)
    return load_world(stack.registry, taxonomy), taxonomy


def _save(items: list[EvalItem], out: Path, *, seed: int) -> None:
    """Public and restricted items in their own files, each one already split."""
    split = assign_splits(items, seed=seed)
    for part in Split:
        chosen = of_split(split, part)
        plain = [item for item in chosen if not item.restricted]
        held = [item for item in chosen if item.restricted]
        if plain:
            write_items(out / part.value / "items.jsonl", plain)
        if held:
            write_items(out / "restricted" / part.value / "items.jsonl", held)
    labels = Counter(item.gold_label.value for item in items)
    print(f"{len(items)} items: {dict(labels)}. Hash {content_hash(items)[:16]}")


def _build_entities(args: argparse.Namespace) -> int:
    stack, today, _ = _stack(args, model=False, log=_scratch_log())
    world, taxonomy = _world(stack)
    names = (
        [line.strip() for line in args.cbuae_names.read_text("utf-8").splitlines() if line.strip()]
        if args.cbuae_names
        else []
    )
    built = build_entity_items(
        world, stack, taxonomy, today=today, seed=args.seed, cbuae_names=names
    )
    _save(list(built.items), args.out, seed=args.seed)
    for line in built.disputed:
        print(f"disputed: {line}")
    return 0


async def _build_messages(args: argparse.Namespace) -> int:
    stack, today, http = _stack(args, model=args.paraphrase, log=_scratch_log())
    world, _ = _world(stack)
    scenarios = sample_scenarios(world, args.per_label, seed=args.seed)
    try:
        built = await build_message_items(
            scenarios,
            stack,
            world,
            today=today,
            seed=args.seed,
            use_model=args.paraphrase,
            people=args.people,
        )
    finally:
        if http is not None:
            await http.aclose()
    _save(list(built.items), args.out, seed=args.seed)
    if built.for_people:
        briefs = args.out / "briefs.jsonl"
        briefs.write_text(
            "".join(
                json.dumps(writing_brief(s), ensure_ascii=False) + "\n" for s in built.for_people
            ),
            encoding="utf-8",
        )
        print(f"{len(built.for_people)} briefs for people to write: {briefs}")
    for line in built.dropped:
        print(f"dropped: {line}")
    print(f"dropped {len(built.dropped)} of {len(scenarios)} scenarios")
    return 0


def _load(paths: list[Path]) -> list[EvalItem]:
    return [item for path in paths for item in read_items(path)]


def _sheet(args: argparse.Namespace) -> int:
    export_sheet(_load(args.items), args.out, annotator=args.annotator, seed=args.seed)
    print(f"blind sheet for {args.annotator}: {args.out}")
    return 0


def _agreement(args: argparse.Namespace) -> int:
    gold = {item.item_id: item.gold_label for item in _load(args.items)}
    result = compare_labels(read_sheet(args.first), read_sheet(args.second), gold)
    print(f"items {result.items}, kappa {result.kappa:.3f}, target met: {result.meets_target}")
    print(f"to discuss: {', '.join(result.disagreements) or 'none'}")
    print(f"both differ from the policy: {', '.join(result.against_policy) or 'none'}")
    return 0


async def _probe(args: argparse.Namespace) -> int:
    """How far plain rules get. A high score means the messages are too easy (§11.2 D)."""
    items = _load(args.items)
    run_dir = args.run_dir or Path(tempfile.mkdtemp(prefix="tessera-probe-"))
    stack, today, _ = _stack(args, model=False, log=run_dir / "events.sqlite")
    plan = load_plan(stack.settings.root / "eval" / "plan.yaml")
    jobs = jobs_for(items, plan, conditions=[SystemCondition.RULES_ONLY], stability=False)
    await Harness(stack, run_dir, today=today).run(jobs)
    table = outcomes_by_condition(items, load_records(run_dir))
    outcomes = list(table[SystemCondition.RULES_ONLY.value].values())
    summary = summarize(outcomes)
    matched = sum(outcome.gold is outcome.predicted for outcome in outcomes)
    print(f"RULES-ONLY matches {matched} of {len(outcomes)}, macro-F1 {summary['macro_f1']:.3f}")
    if (summary["macro_f1"] or 0) > DIFFICULTY_LIMIT:
        print("Too easy: make the messages harder before the test set is frozen.")
    return 0


async def _run(args: argparse.Namespace) -> int:
    items = _load(args.items)
    if args.limit:
        items = items[: args.limit]
    args.run_dir.mkdir(parents=True, exist_ok=True)
    stack, today, http = _stack(args, model=True, log=args.run_dir / "events.sqlite")
    path = stack.settings.root / "eval" / "plan.yaml"
    plan = load_plan(path)
    conditions = (
        [SystemCondition(name.strip()) for name in args.conditions.split(",")]
        if args.conditions
        else None
    )
    jobs = jobs_for(items, plan, conditions=conditions, stability=not args.no_stability)
    harness = Harness(stack, args.run_dir, today=today, plan_hash=plan_hash(path))
    try:
        progress = await harness.run(
            jobs,
            max_requests=args.max_requests,
            hours=args.hours,
            parallel=args.parallel,
            echo=print,
        )
    finally:
        if http is not None:
            await http.aclose()
    print(
        f"{progress.done} done now, {progress.skipped} done before, {progress.failed} failed, "
        f"of {progress.total}. {progress.requests} requests. Stopped: {progress.stopped_because}."
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    root = load_settings().root
    plan = load_plan(root / "eval" / "plan.yaml")
    report = evaluation_report(_load(args.items), load_records(args.run_dir), plan)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(render_text(report))
    return 0


def _power(args: argparse.Namespace) -> int:
    """Redone after the pilot, with the rates it measured (§11.4)."""
    power = mcnemar_power(args.items, args.baseline, args.crew, shared=args.shared)
    print(f"{args.items} items, {args.baseline:.1%} against {args.crew:.1%}: power {power:.2f}")
    return 0


def _leakage(args: argparse.Namespace) -> int:
    stack, _, _ = _stack(args, model=False, log=_scratch_log())
    world, _ = _world(stack)
    root = stack.settings.root
    found = scan(world, [root / "backend" / "prompts", root / "knowledge"])
    for line in found:
        print(f"found: {line}")
    print(f"{len(found)} record names in prompts and rule cards")
    return 1 if found else 0


def _freeze(args: argparse.Namespace) -> int:
    """Write the hash of a finished set, so any later change to it can be seen."""
    items = _load(args.items)
    levels = {item.level.value for item in items}
    manifest = {
        "items": len(items),
        "hash": content_hash(items),
        "levels": sorted(levels),
        "by_split": dict(Counter(item.split.value if item.split else "none" for item in items)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"frozen: {len(items)} items, hash {content_hash(items)[:16]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tessera-eval", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--fiction", action="store_true", help="use the fictional world")
        sub.add_argument("--today", help="the date the records are read as of")
        sub.add_argument("--seed", type=int, default=DEFAULT_SEED)
        sub.add_argument("--thinking", choices=["on", "off"])

    entities = commands.add_parser("entities", help="build the entity-level set")
    common(entities)
    entities.add_argument("--out", type=Path, required=True)
    entities.add_argument("--cbuae-names", type=Path, help="a hand-recorded list, one per line")

    messages = commands.add_parser("messages", help="build the message-level set")
    common(messages)
    messages.add_argument("--out", type=Path, required=True)
    messages.add_argument("--per-label", type=int, default=160)
    messages.add_argument("--paraphrase", action="store_true", help="call the paraphrase model")
    messages.add_argument("--people", action="store_true", help="leave a share for people")

    sheet = commands.add_parser("sheet", help="export a blind labelling sheet")
    sheet.add_argument("--items", type=Path, nargs="+", required=True)
    sheet.add_argument("--annotator", required=True)
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--seed", type=int, default=DEFAULT_SEED)

    agreement = commands.add_parser("agreement", help="compare two filled sheets")
    agreement.add_argument("--items", type=Path, nargs="+", required=True)
    agreement.add_argument("--first", type=Path, required=True)
    agreement.add_argument("--second", type=Path, required=True)

    probe = commands.add_parser("probe", help="how far plain rules get")
    common(probe)
    probe.add_argument("--items", type=Path, nargs="+", required=True)
    probe.add_argument("--run-dir", type=Path)

    run = commands.add_parser("run", help="run the plan, or go on with it")
    common(run)
    run.add_argument("--items", type=Path, nargs="+", required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--conditions", help="comma-separated, for a part of the plan")
    run.add_argument("--limit", type=int, help="only the first N items")
    run.add_argument("--no-stability", action="store_true")
    run.add_argument("--max-requests", type=int)
    run.add_argument("--hours", type=float, help="stop starting cases after this long")
    run.add_argument("--parallel", type=int, default=1, help="cases at once, sharing the limit")

    report = commands.add_parser("report", help="score a run")
    report.add_argument("--items", type=Path, nargs="+", required=True)
    report.add_argument("--run-dir", type=Path, required=True)
    report.add_argument("--out", type=Path)

    power = commands.add_parser("power", help="how likely a true difference is to be found")
    power.add_argument("--items", type=int, default=224)
    power.add_argument("--baseline", type=float, required=True)
    power.add_argument("--crew", type=float, required=True)
    power.add_argument("--shared", type=float, default=0.5)

    leakage = commands.add_parser("leakage", help="look for record names in prompts and cards")
    common(leakage)

    freeze = commands.add_parser("freeze", help="record the hash of a finished set")
    freeze.add_argument("--items", type=Path, nargs="+", required=True)
    freeze.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "entities":
            return _build_entities(args)
        if args.command == "messages":
            return asyncio.run(_build_messages(args))
        if args.command == "sheet":
            return _sheet(args)
        if args.command == "agreement":
            return _agreement(args)
        if args.command == "probe":
            return asyncio.run(_probe(args))
        if args.command == "run":
            return asyncio.run(_run(args))
        if args.command == "report":
            return _report(args)
        if args.command == "power":
            return _power(args)
        if args.command == "leakage":
            return _leakage(args)
        return _freeze(args)
    except PolicyError as exc:
        print(f"tessera-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
