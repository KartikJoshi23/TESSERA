"""The registered metrics (§11.3), computed from what a run recorded and the items' gold labels.

A system that failed to give any result is scored as "Could not verify", because that is what a
person would be told, and the failures are counted and reported beside the scores.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tessera.protocol.common import ResultCode

LABELS = (ResultCode.CONSISTENT, ResultCode.CONFLICTS, ResultCode.UNVERIFIED)

#: Rows: gold result. Columns: predicted result. Fixed in advance (§11.3).
COST_MATRIX: Mapping[ResultCode, Mapping[ResultCode, int]] = {
    ResultCode.CONSISTENT: {
        ResultCode.CONSISTENT: 0,
        ResultCode.CONFLICTS: 3,
        ResultCode.UNVERIFIED: 1,
    },
    ResultCode.CONFLICTS: {
        ResultCode.CONSISTENT: 10,
        ResultCode.CONFLICTS: 0,
        ResultCode.UNVERIFIED: 2,
    },
    ResultCode.UNVERIFIED: {
        ResultCode.CONSISTENT: 8,
        ResultCode.CONFLICTS: 3,
        ResultCode.UNVERIFIED: 0,
    },
}


@dataclass(frozen=True)
class Outcome:
    """One system's answer on one item, joined with that item's gold label."""

    item_id: str
    gold: ResultCode
    predicted: ResultCode
    failed: bool = False
    factors: tuple[str, ...] = ()
    stratum: str = ""
    gold_relevant: tuple[str, ...] = ()
    relevant: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    gold_reasons: tuple[str, ...] = ()
    requests: int = 0
    tokens: int = 0
    seconds: float = 0.0
    cited: int = 0
    cited_valid: int = 0
    banned_terms: int = 0
    telemetry: Mapping[str, Any] = field(default_factory=dict)
    #: Each proposal in order: what it said, and what the Verifier did with it.
    proposals: tuple[tuple[ResultCode, str | None], ...] = ()


def _ratio(top: int | float, bottom: int | float) -> float | None:
    return top / bottom if bottom else None


def confusion(outcomes: Sequence[Outcome]) -> dict[str, dict[str, int]]:
    counts = Counter((outcome.gold, outcome.predicted) for outcome in outcomes)
    return {
        gold.value: {predicted.value: counts[(gold, predicted)] for predicted in LABELS}
        for gold in LABELS
    }


def false_reassurance(outcome: Outcome) -> bool:
    """Said "Consistent" where the record does not support it. The primary safety failure."""
    return outcome.gold is not ResultCode.CONSISTENT and outcome.predicted is ResultCode.CONSISTENT


def false_reassurance_rate(outcomes: Sequence[Outcome]) -> float | None:
    """P(prediction = CONSISTENT | gold ≠ CONSISTENT)."""
    eligible = [o for o in outcomes if o.gold is not ResultCode.CONSISTENT]
    return _ratio(sum(map(false_reassurance, eligible)), len(eligible))


def unsupported_conflict_rate(
    outcomes: Sequence[Outcome], *, on_genuine_only: bool = False
) -> float | None:
    """P(prediction = CONFLICTS | gold ≠ CONFLICTS), or only where gold is CONSISTENT.

    The narrower form is the risk of wrongly implicating a genuine firm.
    """
    if on_genuine_only:
        eligible = [o for o in outcomes if o.gold is ResultCode.CONSISTENT]
    else:
        eligible = [o for o in outcomes if o.gold is not ResultCode.CONFLICTS]
    return _ratio(sum(o.predicted is ResultCode.CONFLICTS for o in eligible), len(eligible))


def per_class(outcomes: Sequence[Outcome]) -> dict[str, dict[str, float | None]]:
    scores: dict[str, dict[str, float | None]] = {}
    for label in LABELS:
        hits = sum(o.gold is label and o.predicted is label for o in outcomes)
        predicted = sum(o.predicted is label for o in outcomes)
        actual = sum(o.gold is label for o in outcomes)
        precision = _ratio(hits, predicted)
        recall = _ratio(hits, actual)
        f1 = (
            _ratio(2 * precision * recall, precision + recall)
            if precision is not None and recall is not None
            else None
        )
        scores[label.value] = {
            "precision": precision,
            "recall": recall,
            "f1": 0.0 if actual and f1 is None else f1,
        }
    return scores


def macro_f1(outcomes: Sequence[Outcome]) -> float | None:
    """The mean F1 over the classes that have gold items."""
    present = {o.gold for o in outcomes}
    values = [
        score["f1"] or 0.0
        for name, score in per_class(outcomes).items()
        if ResultCode(name) in present
    ]
    return _ratio(sum(values), len(values))


def coverage(outcomes: Sequence[Outcome]) -> float | None:
    """How often a system gave a decisive result. It stops a system winning by abstaining."""
    return _ratio(sum(o.predicted is not ResultCode.UNVERIFIED for o in outcomes), len(outcomes))


def decisive_accuracy(outcomes: Sequence[Outcome]) -> float | None:
    decisive = [o for o in outcomes if o.predicted is not ResultCode.UNVERIFIED]
    return _ratio(sum(o.gold is o.predicted for o in decisive), len(decisive))


def cost_weighted_error(outcomes: Sequence[Outcome]) -> float | None:
    return _ratio(sum(COST_MATRIX[o.gold][o.predicted] for o in outcomes), len(outcomes))


def evidence_validity(outcomes: Sequence[Outcome]) -> float | None:
    """The share of cited evidence IDs that exist and were created in the case."""
    return _ratio(sum(o.cited_valid for o in outcomes), sum(o.cited for o in outcomes))


def reason_recall(outcomes: Sequence[Outcome]) -> float | None:
    """On correct answers, the share of the gold reasons a system also gave.

    A right result for the wrong reason is luck. This stands in for evidence completeness (§11.3)
    until the human ratings exist.
    """
    right = [o for o in outcomes if o.gold is o.predicted and o.gold_reasons]
    expected = sum(len(o.gold_reasons) for o in right)
    return _ratio(sum(len(set(o.gold_reasons) & set(o.reasons)) for o in right), expected)


def jurisdiction_scores(outcomes: Sequence[Outcome]) -> dict[str, float | None]:
    """Per-item Jaccard similarity, and micro precision and recall over (item, regulator) pairs."""
    judged = [o for o in outcomes if o.gold_relevant]
    if not judged:
        return {"jaccard": None, "precision": None, "recall": None}
    jaccards = []
    true_positive = predicted = actual = 0
    for outcome in judged:
        gold, found = set(outcome.gold_relevant), set(outcome.relevant)
        jaccards.append(len(gold & found) / len(gold | found))
        true_positive += len(gold & found)
        predicted += len(found)
        actual += len(gold)
    return {
        "jaccard": sum(jaccards) / len(jaccards),
        "precision": _ratio(true_positive, predicted),
        "recall": _ratio(true_positive, actual),
    }


#: Items that turn on a scope rule: Category 5 with FX, or an IPA holder taking clients (§11.3).
_SCOPE_FACTORS = frozenset({"F7"})
_SCOPE_STRATA = frozenset({"E6", "E8"})


def scope_rule_accuracy(outcomes: Sequence[Outcome]) -> float | None:
    scoped = [o for o in outcomes if _SCOPE_FACTORS & set(o.factors) or o.stratum in _SCOPE_STRATA]
    return _ratio(sum(o.gold is o.predicted for o in scoped), len(scoped))


def _percentile(values: Sequence[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(int(share * len(ordered)), len(ordered) - 1)]


def compute_cost(outcomes: Sequence[Outcome]) -> dict[str, float | None]:
    count = len(outcomes)
    seconds = [o.seconds for o in outcomes]
    return {
        "requests_per_case": _ratio(sum(o.requests for o in outcomes), count),
        "tokens_per_case": _ratio(sum(o.tokens for o in outcomes), count),
        "seconds_p50": _percentile(seconds, 0.5),
        "seconds_p95": _percentile(seconds, 0.95),
    }


def veto_scores(outcomes: Sequence[Outcome]) -> dict[str, float | None]:
    """Whether vetoes land on the proposals that deserve them.

    Precision is the share of vetoed proposals that were wrong. Recall is the share of wrong
    "Consistent" proposals that were vetoed, which is the failure a Verifier exists to stop. Rescue
    is how often a first proposal that was wrong ended as a right answer.
    """
    vetoed = [
        (o.gold, result) for o in outcomes for result, verifier in o.proposals if verifier == "VETO"
    ]
    risky = [
        verifier == "VETO"
        for o in outcomes
        for result, verifier in o.proposals[:1]
        if result is ResultCode.CONSISTENT and o.gold is not ResultCode.CONSISTENT
    ]
    wrong_first = [o for o in outcomes if o.proposals and o.proposals[0][0] is not o.gold]
    return {
        "veto_precision": _ratio(sum(gold is not result for gold, result in vetoed), len(vetoed)),
        "veto_recall": _ratio(sum(risky), len(risky)),
        "rescue_rate": _ratio(sum(o.predicted is o.gold for o in wrong_first), len(wrong_first)),
    }


def coordination(outcomes: Sequence[Outcome]) -> dict[str, float | None]:
    """How the crew's mechanisms behaved."""
    with_telemetry = [o for o in outcomes if o.telemetry]
    count = len(with_telemetry)
    if not count:
        return {}
    sent = sum(o.telemetry["challenges"]["sent"] for o in with_telemetry)
    revised = sum(o.telemetry["challenges"]["revisions"] for o in with_telemetry)
    vetoed = [o for o in with_telemetry if o.telemetry["verifier"]["vetoes"]]
    return {
        "conflicts_per_case": _ratio(
            sum(o.telemetry["conflicts"]["total"] for o in with_telemetry), count
        ),
        "challenges_per_case": _ratio(sent, count),
        "revision_rate": _ratio(revised, sent),
        "veto_rate": _ratio(len(vetoed), count),
        **veto_scores(with_telemetry),
        "conformity_flags_per_case": _ratio(
            sum(o.telemetry["conformity_flags"] for o in with_telemetry), count
        ),
        "repairs_per_case": _ratio(sum(o.telemetry["repairs"] for o in with_telemetry), count),
    }


def summarize(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    """Every metric for one system on one level of the evaluation."""
    return {
        "items": len(outcomes),
        "failures": sum(o.failed for o in outcomes),
        "false_reassurance_rate": false_reassurance_rate(outcomes),
        "unsupported_conflict_rate": unsupported_conflict_rate(outcomes),
        "unsupported_conflict_on_genuine": unsupported_conflict_rate(
            outcomes, on_genuine_only=True
        ),
        "macro_f1": macro_f1(outcomes),
        "per_class": per_class(outcomes),
        "coverage": coverage(outcomes),
        "decisive_accuracy": decisive_accuracy(outcomes),
        "cost_weighted_error": cost_weighted_error(outcomes),
        "evidence_validity": evidence_validity(outcomes),
        "reason_recall": reason_recall(outcomes),
        "jurisdiction": jurisdiction_scores(outcomes),
        "scope_rule_accuracy": scope_rule_accuracy(outcomes),
        "banned_terms": sum(o.banned_terms for o in outcomes),
        "compute": compute_cost(outcomes),
        "coordination": coordination(outcomes),
        "confusion": confusion(outcomes),
    }
