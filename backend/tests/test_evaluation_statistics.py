"""The registered statistics and metrics, against values worked out by hand."""

import pytest

from tessera.evaluation.metrics import (
    Outcome,
    confusion,
    cost_weighted_error,
    coverage,
    decisive_accuracy,
    evidence_validity,
    false_reassurance_rate,
    jurisdiction_scores,
    macro_f1,
    per_class,
    reason_recall,
    scope_rule_accuracy,
    summarize,
    unsupported_conflict_rate,
    veto_scores,
)
from tessera.evaluation.statistics import (
    cohen_kappa,
    exact_mcnemar,
    fleiss_kappa,
    holm_bonferroni,
    mcnemar_power,
    paired_bootstrap,
)
from tessera.protocol.common import ResultCode

C = ResultCode.CONSISTENT
X = ResultCode.CONFLICTS
U = ResultCode.UNVERIFIED


def outcome(gold, predicted, **changes):
    return Outcome(item_id="i", gold=gold, predicted=predicted, **changes)


# ------------------------------------------------------------------ statistics


def test_mcnemar_matches_a_worked_value():
    # Two-sided exact test with 1 against 9 discordant pairs: 2 * (1 + 10) / 2**10.
    assert exact_mcnemar(1, 9) == pytest.approx(22 / 1024)


def test_mcnemar_is_symmetric_and_needs_a_difference():
    assert exact_mcnemar(3, 8) == exact_mcnemar(8, 3)
    assert exact_mcnemar(0, 0) == 1.0
    assert exact_mcnemar(5, 5) == 1.0


def test_holm_adjusts_in_step_and_never_lowers_a_later_value():
    adjusted = holm_bonferroni({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted["a"] == pytest.approx(0.03)
    assert adjusted["c"] == pytest.approx(0.06)
    assert adjusted["b"] == pytest.approx(0.06)


def test_holm_caps_at_one():
    assert holm_bonferroni({"a": 0.9, "b": 0.8})["a"] == 1.0


def test_bootstrap_is_reproducible_and_brackets_the_estimate():
    data = [1.0] * 30 + [0.0] * 70
    mean = lambda sample: sum(sample) / len(sample)  # noqa: E731
    first = paired_bootstrap(data, mean, resamples=2000)
    second = paired_bootstrap(data, mean, resamples=2000)
    assert first == second
    assert first.low < first.estimate < first.high
    assert first.estimate == pytest.approx(0.3)
    assert first.low == pytest.approx(0.21, abs=0.03)
    assert first.high == pytest.approx(0.39, abs=0.03)


def test_bootstrap_says_when_the_interval_clears_zero():
    positive = paired_bootstrap([1.0] * 50, lambda s: sum(s) / len(s), resamples=200)
    assert positive.excludes_zero()


def test_cohen_kappa_matches_a_worked_value():
    first = ["a"] * 20 + ["a"] * 5 + ["b"] * 10 + ["b"] * 15
    second = ["a"] * 20 + ["b"] * 5 + ["a"] * 10 + ["b"] * 15
    # Observed 0.7, chance 0.5, from the standard textbook table.
    assert cohen_kappa(first, second) == pytest.approx(0.4)


def test_cohen_kappa_is_one_for_perfect_agreement():
    assert cohen_kappa(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0


def test_fleiss_kappa_matches_the_published_example():
    # Fleiss (1971) style table: 10 items, 14 raters, 5 categories. Result 0.21.
    table = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    rows = [[str(k) for k, count in enumerate(row) for _ in range(count)] for row in table]
    assert fleiss_kappa(rows) == pytest.approx(0.21, abs=0.005)


def test_fleiss_kappa_refuses_uneven_rows():
    with pytest.raises(ValueError, match="same number"):
        fleiss_kappa([["a", "b"], ["a"]])


def test_power_rises_with_the_size_of_the_effect():
    weak = mcnemar_power(224, 0.10, 0.08, simulations=300)
    strong = mcnemar_power(224, 0.10, 0.03, simulations=300)
    assert strong > weak
    assert 0.5 < strong <= 1.0


# ------------------------------------------------------------------ metrics


def test_false_reassurance_counts_only_items_that_are_not_consistent():
    outcomes = [outcome(X, C), outcome(X, X), outcome(U, C), outcome(U, U), outcome(C, C)]
    assert false_reassurance_rate(outcomes) == pytest.approx(0.5)


def test_false_reassurance_is_undefined_with_nothing_to_measure():
    assert false_reassurance_rate([outcome(C, C)]) is None


def test_unsupported_conflict_has_a_narrow_form_for_genuine_firms():
    outcomes = [outcome(C, X), outcome(C, C), outcome(U, X), outcome(X, X)]
    assert unsupported_conflict_rate(outcomes) == pytest.approx(2 / 3)
    assert unsupported_conflict_rate(outcomes, on_genuine_only=True) == pytest.approx(0.5)


def test_macro_f1_is_the_mean_of_the_classes_present():
    outcomes = [outcome(C, C), outcome(C, U), outcome(X, X), outcome(X, X)]
    # C: p 1, r 0.5, f1 2/3. X: 1. U has no gold items, so it is left out.
    assert macro_f1(outcomes) == pytest.approx((2 / 3 + 1) / 2)


def test_a_class_never_found_scores_zero_not_nothing():
    scores = per_class([outcome(C, U), outcome(C, U)])
    assert scores["CONSISTENT"]["f1"] == 0.0


def test_coverage_stops_a_system_winning_by_abstaining():
    outcomes = [outcome(X, U), outcome(C, U), outcome(U, U), outcome(C, C)]
    assert coverage(outcomes) == pytest.approx(0.25)
    assert decisive_accuracy(outcomes) == 1.0


def test_cost_uses_the_registered_matrix():
    assert cost_weighted_error([outcome(X, C)]) == 10
    assert cost_weighted_error([outcome(U, C), outcome(C, X)]) == pytest.approx(5.5)


def test_evidence_validity_is_the_share_of_real_citations():
    outcomes = [outcome(C, C, cited=4, cited_valid=3), outcome(C, C, cited=6, cited_valid=6)]
    assert evidence_validity(outcomes) == pytest.approx(0.9)


def test_jurisdiction_scores_are_per_item_and_over_pairs():
    outcomes = [
        outcome(C, C, gold_relevant=("CMA",), relevant=("CMA",)),
        outcome(C, C, gold_relevant=("CMA", "VARA"), relevant=("VARA", "DFSA")),
    ]
    scores = jurisdiction_scores(outcomes)
    assert scores["jaccard"] == pytest.approx((1 + 1 / 3) / 2)
    assert scores["precision"] == pytest.approx(2 / 3)
    assert scores["recall"] == pytest.approx(2 / 3)


def test_scope_accuracy_reads_only_the_scope_items():
    outcomes = [
        outcome(X, X, factors=("F7",)),
        outcome(X, U, stratum="E8"),
        outcome(X, U, factors=("F2",)),
    ]
    assert scope_rule_accuracy(outcomes) == pytest.approx(0.5)


def test_confusion_has_every_cell():
    table = confusion([outcome(X, C)])
    assert table["CONFLICTS"]["CONSISTENT"] == 1
    assert table["UNVERIFIED"]["UNVERIFIED"] == 0


def test_a_summary_reports_failures_beside_the_scores():
    summary = summarize([outcome(X, U, failed=True), outcome(C, C)])
    assert summary["failures"] == 1
    assert summary["items"] == 2


def test_veto_scores_judge_the_proposal_not_the_final_answer():
    outcomes = [
        # A wrong "Consistent" was vetoed, and the second proposal got it right: a rescue.
        outcome(X, X, proposals=((C, "VETO"), (X, "APPROVE"))),
        # A right proposal was vetoed, and the case ended as "Could not verify": a false veto.
        outcome(C, U, proposals=((C, "VETO"), (U, "VETO"))),
        # A wrong "Consistent" went through: a veto that should have happened.
        outcome(U, C, proposals=((C, "APPROVE"),)),
    ]
    scores = veto_scores(outcomes)
    # Vetoed: C on gold X (wrong), C on gold C (right), U on gold C (wrong).
    assert scores["veto_precision"] == pytest.approx(2 / 3)
    assert scores["veto_recall"] == pytest.approx(1 / 2)
    assert scores["rescue_rate"] == pytest.approx(1 / 2)


def test_reason_recall_reads_only_right_answers():
    outcomes = [
        outcome(X, X, gold_reasons=("HC1", "HC2"), reasons=("HC1",)),
        outcome(X, U, gold_reasons=("HC3",), reasons=("U1",)),
        outcome(U, U, gold_reasons=("U2",), reasons=("U2",)),
    ]
    assert reason_recall(outcomes) == pytest.approx(2 / 3)


def test_a_summary_needs_no_telemetry():
    assert summarize([outcome(C, C)])["coordination"] == {}
