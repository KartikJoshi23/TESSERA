"""From records to the registered analyses (§11.3, §11.4).

Entity-level and message-level results are computed apart and never pooled. Every comparison is
paired: it uses only the items both systems answered. All results are reported, confirmed or not.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from tessera.evaluation.items import EvalItem, Level
from tessera.evaluation.metrics import (
    Outcome,
    false_reassurance,
    false_reassurance_rate,
    macro_f1,
    summarize,
)
from tessera.evaluation.plan import Comparison, RunPlan
from tessera.evaluation.statistics import (
    exact_mcnemar,
    fleiss_kappa,
    holm_bonferroni,
    paired_bootstrap,
)
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import ResultCode

_Pair = tuple[Outcome, Outcome]


def to_outcome(item: EvalItem, record: dict[str, Any]) -> Outcome:
    """Join a record with its gold label. This is the only place the two meet."""
    return Outcome(
        item_id=item.item_id,
        gold=item.gold_label,
        predicted=ResultCode(record["result"]),
        failed=bool(record.get("failures")),
        factors=item.factors,
        stratum=item.stratum,
        gold_relevant=item.gold_relevant,
        relevant=tuple(record.get("relevant", ())),
        reasons=(*record.get("hard_conflicts", ()), *record.get("unverified_reasons", ())),
        gold_reasons=item.gold_reasons,
        requests=record.get("requests", 0),
        tokens=record.get("tokens", 0),
        seconds=record.get("seconds", 0.0),
        cited=record.get("cited", 0),
        cited_valid=record.get("cited_valid", 0),
        banned_terms=record.get("banned_terms", 0),
        telemetry=record.get("telemetry", {}),
        proposals=tuple(
            (ResultCode(step["result"]), step.get("verifier"))
            for step in record.get("proposals", ())
        ),
    )


def outcomes_by_condition(
    items: Sequence[EvalItem], records: Sequence[dict[str, Any]], *, run: int = 0
) -> dict[str, dict[str, Outcome]]:
    known = {item.item_id: item for item in items}
    table: dict[str, dict[str, Outcome]] = defaultdict(dict)
    for record in records:
        item = known.get(record["item_id"])
        if item is not None and record["run"] == run:
            table[record["condition"]][item.item_id] = to_outcome(item, record)
    return table


def _pairs(table: dict[str, dict[str, Outcome]], comparison: Comparison) -> list[_Pair]:
    first = table.get(comparison.first.value, {})
    second = table.get(comparison.second.value, {})
    return [(first[item], second[item]) for item in sorted(set(first) & set(second))]


def _difference(metric: str, pairs: Sequence[_Pair]) -> float:
    score = false_reassurance_rate if metric == "false_reassurance" else macro_f1
    first = score([a for a, _ in pairs])
    second = score([b for _, b in pairs])
    return (first or 0.0) - (second or 0.0)


def compare(table: dict[str, dict[str, Outcome]], comparison: Comparison) -> dict[str, Any]:
    pairs = _pairs(table, comparison)
    if not pairs:
        return {"name": comparison.name, "pairs": 0}
    metric = comparison.metric
    interval = paired_bootstrap(pairs, lambda sample: _difference(metric, sample))
    report: dict[str, Any] = {
        "name": comparison.name,
        "first": comparison.first.value,
        "second": comparison.second.value,
        "metric": metric,
        "pairs": len(pairs),
        "difference": interval.estimate,
        "ci_low": interval.low,
        "ci_high": interval.high,
    }
    if metric == "false_reassurance":
        eligible = [(a, b) for a, b in pairs if a.gold is not ResultCode.CONSISTENT]
        only_first = sum(false_reassurance(a) and not false_reassurance(b) for a, b in eligible)
        only_second = sum(false_reassurance(b) and not false_reassurance(a) for a, b in eligible)
        report |= {
            "only_first": only_first,
            "only_second": only_second,
            "p_value": exact_mcnemar(only_first, only_second),
        }
    return report


def stability(
    items: Sequence[EvalItem],
    records: Sequence[dict[str, Any]],
    condition: SystemCondition,
    runs: int,
) -> dict[str, Any]:
    """How far repeat runs agree. An item needs all of its runs to count."""
    by_item: dict[str, dict[int, str]] = defaultdict(dict)
    known = {item.item_id for item in items}
    for record in records:
        same_system = record["condition"] == condition.value and record["item_id"] in known
        if same_system and record["run"] >= 1:
            by_item[record["item_id"]][record["run"]] = record["result"]
    rows = [list(found.values()) for found in by_item.values() if len(found) == runs]
    if not rows:
        return {"condition": condition.value, "items": 0}
    flips = sum(len(set(row)) > 1 for row in rows)
    return {
        "condition": condition.value,
        "items": len(rows),
        "fleiss_kappa": fleiss_kappa(rows),
        "flip_rate": flips / len(rows),
    }


def level_report(
    items: Sequence[EvalItem], records: Sequence[dict[str, Any]], plan: RunPlan, level: Level
) -> dict[str, Any]:
    """Everything for one level of the evaluation."""
    chosen = [item for item in items if item.level is level]
    table = outcomes_by_condition(chosen, records)
    registered = [compare(table, comparison) for comparison in plan.registered]
    secondary = [compare(table, comparison) for comparison in plan.secondary]
    tested = {c["name"]: c["p_value"] for c in secondary if "p_value" in c}
    adjusted = holm_bonferroni(tested) if tested else {}
    for comparison in secondary:
        if comparison["name"] in adjusted:
            comparison["p_holm"] = adjusted[comparison["name"]]
    return {
        "level": level.value,
        "items": len(chosen),
        "systems": {name: summarize(list(found.values())) for name, found in table.items()},
        "registered": registered,
        "secondary": secondary,
        "non_inferiority": _non_inferiority(registered, plan.non_inferiority_margin),
        "stability": [
            stability(chosen, records, condition, runs)
            for condition, runs in plan.stability.runs.items()
        ],
    }


def _non_inferiority(registered: Sequence[dict[str, Any]], margin: float) -> dict[str, Any]:
    """H2: the whole interval must sit above the margin, so noise cannot pass as a tie."""
    usefulness = next((c for c in registered if c.get("metric") == "macro_f1"), None)
    if not usefulness or not usefulness.get("pairs"):
        return {"tested": False}
    return {
        "tested": True,
        "margin": margin,
        "ci_low": usefulness["ci_low"],
        "holds": usefulness["ci_low"] > -margin,
    }


def evaluation_report(
    items: Sequence[EvalItem], records: Sequence[dict[str, Any]], plan: RunPlan
) -> dict[str, Any]:
    return {
        "levels": {
            level.value: level_report(items, records, plan, level)
            for level in Level
            if any(item.level is level for item in items)
        }
    }


def _shown(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def render_text(report: dict[str, Any]) -> str:
    """A plain summary for the terminal. The JSON holds everything."""
    lines: list[str] = []
    for level in report["levels"].values():
        lines.append(f"\n{level['level'].upper()} LEVEL: {level['items']} items")
        lines.append(
            f"{'system':<14}{'n':>5}{'FRR':>8}{'macro-F1':>10}{'cover':>8}{'req/case':>10}"
        )
        for name, system in level["systems"].items():
            lines.append(
                f"{name:<14}{system['items']:>5}"
                f"{_shown(system['false_reassurance_rate']):>8}"
                f"{_shown(system['macro_f1']):>10}"
                f"{_shown(system['coverage']):>8}"
                f"{_shown(system['compute']['requests_per_case']):>10}"
            )
        for comparison in level["registered"] + level["secondary"]:
            if not comparison.get("pairs"):
                continue
            lines.append(
                f"{comparison['name']}: {comparison['first']} minus {comparison['second']} = "
                f"{comparison['difference']:+.3f} "
                f"[{comparison['ci_low']:+.3f}, {comparison['ci_high']:+.3f}]"
                + (f", p={comparison['p_value']:.4f}" if "p_value" in comparison else "")
            )
    return "\n".join(lines)
