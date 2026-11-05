"""``tessera-eval``: build datasets, run the plan, and report it.

``--fiction`` works on the fictional world, under ``runs/eval/``. That is for dry runs of the whole
pipeline before any real record is loaded. Its numbers say how the machinery behaves, and they are
not evaluation results.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
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
from tessera.evaluation.components import component_report
from tessera.evaluation.entities import build_entity_items
from tessera.evaluation.firms import load_world
from tessera.evaluation.freezing import fingerprint, freeze_manifest, frozen_problems, pin_run
from tessera.evaluation.harness import Harness, load_records
from tessera.evaluation.items import EvalItem, Split, content_hash, read_items, write_items
from tessera.evaluation.leakage import scan
from tessera.evaluation.messages import build_message_items, import_written
from tessera.evaluation.metrics import summarize
from tessera.evaluation.plan import jobs_for, load_plan, plan_hash
from tessera.evaluation.readiness import readiness
from tessera.evaluation.report import evaluation_report, outcomes_by_condition, render_text
from tessera.evaluation.review import compare_labels, export_sheet, read_sheet, settle
from tessera.evaluation.scenarios import (
    Scenario,
    sample_scenarios,
    scenario_from_json,
    scenario_to_json,
)
from tessera.evaluation.splits import assign_splits, balanced_sample, of_split
from tessera.evaluation.statistics import mcnemar_power
from tessera.evaluation.writing import writing_brief
from tessera.governance.policies import load_decision_policy
from tessera.knowledge import load_activity_taxonomy
from tessera.llm.config import load_models_policy
from tessera.llm.stack import NoModelTransport, build_live_transport
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import ResultCode

BRIEFS = "briefs.csv"
SCENARIOS = "scenarios-for-people.jsonl"
DEFAULT_SEED = 20261105
#: RULES-ONLY above this on the development split means the messages are too formulaic (§11.2 D).
DIFFICULTY_LIMIT = 0.7


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
    transport: Any = NoModelTransport()
    http = None
    if model:
        transport, http = build_live_transport(settings, models)
    return build_stack(settings, transport, EventStore(log), models), today, http


def _scratch_log() -> Path:
    return Path(tempfile.mkdtemp(prefix="tessera-eval-")) / "events.sqlite"


def _world(stack: CrewStack) -> Any:
    taxonomy = load_activity_taxonomy(stack.settings.knowledge_dir)
    return load_world(stack.registry, taxonomy), taxonomy


def restricted_home(out: Path) -> Path:
    """Where DFSA-derived work for ``out`` goes: a sibling ``restricted`` folder.

    ``datasets/message_level`` becomes ``datasets/restricted/message_level``, so deleting
    ``datasets/restricted`` removes every DFSA value, as the data-governance notes promise.
    """
    return out.parent / "restricted" / out.name


def _file_for(out: Path, part: Split, *, restricted: bool) -> Path:
    return (restricted_home(out) if restricted else out) / part.value / "items.jsonl"


def _write_split(items: list[EvalItem], out: Path, *, adding: bool = False) -> None:
    """Public and restricted items in their own files. ``adding`` keeps what the files hold."""
    for part in Split:
        for restricted in (False, True):
            path = _file_for(out, part, restricted=restricted)
            new = [i for i in of_split(items, part) if i.restricted is restricted]
            old = read_items(path) if adding and path.exists() else []
            if new or old:
                write_items(path, [*old, *new])
            elif path.exists():
                path.unlink()  # left by an earlier build, and not part of this one


def _save(items: list[EvalItem], out: Path, *, seed: int) -> None:
    _write_split(assign_splits(items, seed=seed), out)
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
    for restricted in (False, True):
        people = [s for s in built.for_people if s.restricted is restricted]
        if people:
            folder = restricted_home(args.out) if restricted else args.out
            _write_briefs(people, folder)
            print(f"{len(people)} briefs for people to write: {folder / BRIEFS}")
    for line in built.dropped:
        print(f"dropped: {line}")
    print(f"dropped {len(built.dropped)} of {len(scenarios)} scenarios")
    return 0


def _write_briefs(scenarios: list[Scenario], folder: Path) -> None:
    """A sheet for the writers, and the scenarios it came from, to check their messages against."""
    folder.mkdir(parents=True, exist_ok=True)
    briefs = [writing_brief(scenario) for scenario in scenarios]
    with (folder / BRIEFS).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(briefs[0]))
        writer.writeheader()
        writer.writerows(briefs)
    lines = (json.dumps(scenario_to_json(s), ensure_ascii=False) for s in scenarios)
    (folder / SCENARIOS).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _written(args: argparse.Namespace) -> int:
    """Bring in what people wrote. Each message passes the same checks as generated ones."""
    stack, today, _ = _stack(args, model=False, log=_scratch_log())
    world, _ = _world(stack)
    with args.briefs.open(encoding="utf-8", newline="") as handle:
        written = {row["scenario_id"]: row["text"] for row in csv.DictReader(handle)}
    lines = (args.briefs.parent / SCENARIOS).read_text(encoding="utf-8").splitlines()
    scenarios = [scenario_from_json(json.loads(line)) for line in lines if line.strip()]
    built = import_written(written, scenarios, stack, world, today=today)
    _write_split(assign_splits(list(built.items), seed=args.seed), args.out, adding=True)
    for line in built.dropped:
        print(f"dropped: {line}")
    print(f"added {len(built.items)} messages, dropped {len(built.dropped)}")
    return 0


def _settle(args: argparse.Namespace) -> int:
    """Apply what discussion settled. A blank label drops the item, and every drop is listed."""
    with args.decisions.open(encoding="utf-8", newline="") as handle:
        decisions = {
            row["item_id"]: ResultCode(row["label"].strip().upper())
            if row["label"].strip()
            else None
            for row in csv.DictReader(handle)
        }
    kept, dropped = settle(read_items(args.items), decisions)
    write_items(args.items, kept)
    print(f"{len(kept)} items kept, {len(dropped)} dropped: {', '.join(dropped) or 'none'}")
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
    if not outcomes:
        print("tessera-eval: no items to probe")
        return 2
    summary = summarize(outcomes)
    matched = sum(outcome.gold is outcome.predicted for outcome in outcomes)
    print(f"RULES-ONLY matches {matched} of {len(outcomes)}, macro-F1 {summary['macro_f1']:.3f}")
    if (summary["macro_f1"] or 0) > DIFFICULTY_LIMIT:
        print("Too easy: make the messages harder before the test set is frozen.")
    return 0


def _sealed_problems(
    args: argparse.Namespace, items: list[EvalItem], print_: dict[str, str]
) -> list[str]:
    """Real test items run only against a freeze that still matches (§11.2 D)."""
    if args.fiction or not any(item.split is Split.TEST for item in items):
        return []
    if args.frozen is None:
        return ["test items need --frozen: the test split is sealed until a freeze"]
    return frozen_problems(json.loads(args.frozen.read_text("utf-8")), items, print_)


async def _run(args: argparse.Namespace) -> int:
    items = _load(args.items)
    if args.limit:
        items = balanced_sample(items, args.limit, seed=args.seed)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    stack, today, http = _stack(args, model=True, log=args.run_dir / "events.sqlite")
    path = stack.settings.root / "eval" / "plan.yaml"
    plan = load_plan(path)
    print_ = fingerprint(stack.settings, stack.models)
    problems = _sealed_problems(args, items, print_)
    today, pinned = pin_run(
        args.run_dir,
        print_,
        today,
        stated=date.fromisoformat(args.today) if args.today else None,
    )
    if problems or pinned:
        for line in (*problems, *pinned):
            print(f"tessera-eval: {line}", file=sys.stderr)
        if http is not None:
            await http.aclose()
        return 2
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
    items = _load(args.items)
    if args.split == "all":
        chosen = items
    elif args.split:
        chosen = of_split(items, Split(args.split))
    elif len({item.split for item in items}) > 1:
        print("tessera-eval: these items span dev and test, so choose one with --split")
        return 2
    else:
        chosen = items
    report = evaluation_report(chosen, load_records(args.run_dir), plan)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(render_text(report))
    return 0


def _readiness(args: argparse.Namespace) -> int:
    """What the real evaluation still needs. It changes nothing."""
    stack, _, _ = _stack(args, model=False, log=_scratch_log())
    world, taxonomy = _world(stack)
    root = stack.settings.root
    checks = readiness(stack.registry, world, taxonomy, root, seed=args.seed)
    for check in checks:
        print(f"[{'ok' if check.done else 'to do'}] {check.name}: {check.detail}")
    waiting = sum(not check.done for check in checks)
    print("Ready to build the datasets." if not waiting else f"{waiting} things still to do.")
    return 0


def _components(args: argparse.Namespace) -> int:
    """Whether the tools work, apart from any model (§11.2 C)."""
    stack, _, _ = _stack(args, model=False, log=_scratch_log())
    world, _ = _world(stack)
    thresholds = load_decision_policy(stack.settings.policies_dir).thresholds
    items = _load(args.items) if args.items else []
    for name, score in component_report(world, thresholds, items, seed=args.seed).items():
        print(
            f"{name}: found {score.found} of {score.positives}, "
            f"false alarms {score.false_alarms} of {score.negatives}"
        )
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


def _lab(args: argparse.Namespace) -> int:
    """Counts for the Lab's development view. It holds only IDs, result codes and costs."""
    if not args.fiction:
        print("tessera-eval: only a fictional run may go in the Lab's development view")
        return 2
    gold = {item.item_id: item.gold_label.value for item in _load(args.items)}
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for record in load_records(args.run_dir):
        if record["run"] == 0 and record["item_id"] in gold:
            by_condition.setdefault(record["condition"], []).append(
                {
                    "case": record["item_id"],
                    "gold": gold[record["item_id"]],
                    "result": record["result"],
                    "requests": record["requests"],
                    "tokens": record["tokens"],
                    "seconds": round(record["seconds"]),
                }
            )
    runs = [
        {"run": name, "condition": name, "rate_limited": 0, "cases": cases}
        for name, cases in by_condition.items()
    ]
    args.out.write_text(json.dumps({"runs": runs}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(runs)} systems to {args.out}")
    if args.report:
        plan = load_plan(load_settings().root / "eval" / "plan.yaml")
        report = evaluation_report(_load(args.items), load_records(args.run_dir), plan)
        args.report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(f"wrote the report to {args.report}")
    return 0


def _freeze(args: argparse.Namespace) -> int:
    """Write the hash of a finished set, so any later change to it can be seen."""
    items = _load(args.items)
    settings = load_settings(mode=Mode.RESEARCH_INTERNAL)
    models = load_models_policy(settings.policies_dir)
    if args.thinking:
        models = models.with_thinking(args.thinking == "on")
    manifest = freeze_manifest(items, fingerprint(settings, models))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"frozen: {len(items)} items, hash {content_hash(items)[:16]}")
    return 0


def _at_least_one(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


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
    run.add_argument("--limit", type=int, help="N items, balanced across the labels")
    run.add_argument("--frozen", type=Path, help="the freeze that real test items must match")
    run.add_argument("--no-stability", action="store_true")
    run.add_argument("--max-requests", type=int)
    run.add_argument("--hours", type=float, help="stop starting cases after this long")
    run.add_argument(
        "--parallel", type=_at_least_one, default=1, help="cases at once, sharing the limit"
    )

    report = commands.add_parser("report", help="score a run")
    report.add_argument("--items", type=Path, nargs="+", required=True)
    report.add_argument("--run-dir", type=Path, required=True)
    report.add_argument("--out", type=Path)
    report.add_argument("--split", choices=["dev", "test", "all"], help="needed if items span both")

    ready = commands.add_parser("readiness", help="what the real evaluation still needs")
    common(ready)

    components = commands.add_parser("components", help="check the tools, with no model")
    common(components)
    components.add_argument("--items", type=Path, nargs="*")

    lab = commands.add_parser("lab", help="counts from a fictional run, for the Lab")
    lab.add_argument("--fiction", action="store_true")
    lab.add_argument("--items", type=Path, nargs="+", required=True)
    lab.add_argument("--run-dir", type=Path, required=True)
    lab.add_argument("--out", type=Path, required=True)
    lab.add_argument("--report", type=Path, help="also write the full report, for the charts")

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
    freeze.add_argument("--thinking", choices=["on", "off"])

    written = commands.add_parser("written", help="bring in messages people wrote")
    common(written)
    written.add_argument("--briefs", type=Path, required=True, help="the filled-in briefs.csv")
    written.add_argument("--out", type=Path, required=True)

    settled = commands.add_parser("settle", help="apply labels settled by discussion")
    settled.add_argument("--items", type=Path, required=True)
    settled.add_argument("--decisions", type=Path, required=True, help="item_id,label as CSV")
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
        if args.command == "readiness":
            return _readiness(args)
        if args.command == "components":
            return _components(args)
        if args.command == "lab":
            return _lab(args)
        if args.command == "power":
            return _power(args)
        if args.command == "leakage":
            return _leakage(args)
        if args.command == "written":
            return _written(args)
        if args.command == "settle":
            return _settle(args)
        return _freeze(args)
    except PolicyError as exc:
        print(f"tessera-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
