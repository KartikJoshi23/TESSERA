# Write-up skeleton

This is the frame for the paper, written before any test result exists. **No number goes here by
hand.** Every table and figure comes from `tessera-eval paper`, every failure count from
`tessera-eval failure-codes`, and every claim cites the file it came from. Fictional development
runs are never reported as results.

Working titles (implementation-plan.md §17.1):

- *Do Agent Crews Reduce False Reassurance? A Controlled Study of Multi-Regulator Licence
  Verification in the UAE*
- *Coordination or Compute? Evidence-Linked Verification of Investment Offers Across Fragmented
  Financial Registers*

## Abstract (write last)

One sentence each, in this order: the problem; the task and its three results; the crew and the
mandatory single-agent baseline with the same tools; the data, with entity-level and message-level
results kept apart; the primary result on false reassurance, with its interval; what the mechanism
analysis shows; what follows for anyone building such a tool. State the null if it is null.

## 1. Introduction

- **The problem.** Investment offers borrow the names, reference numbers and addresses of licensed
  firms. In the UAE the official records sit with five regulators (CMA, CBUAE, DFSA, ADGM FSRA and
  VARA), so checking one offer means checking several registers and alert lists, and comparing
  contact details with the record.
- **The question.** Does a crew of agents that share findings, challenge each other and pass a
  Verifier give false reassurance less often than one agent with the same tools and knowledge?
- **Why it is hard to answer fairly.** Crews spend more compute. The comparison therefore holds
  knowledge equal, matches compute with extra baselines, and ablates each mechanism (§10).
- **Contributions.** The six in implementation-plan.md §17.2, cut to those the results support.

## 2. Related work

From implementation-plan.md §17.4: multi-agent failure analysis (MAST); comparisons at equal
compute; debate against voting; scaling laws for agent systems; production multi-agent systems and
token use; fact verification with retrieved evidence; selective prediction and abstention; entity
resolution for KYC; typosquatting detection.

## 3. The task

- **Three results, never a verdict:** "Consistent with the official record", "Conflicts with the
  official record", "Could not verify", each with linked evidence and a statement of what was not
  checked. The tool never calls a firm a scam and never recommends an investment.
- **The decision policy** (HC1–HC6, K1–K7, U1–U9), fixed before the data.
- **Coverage.** Phase 1 checks the CMA, DFSA and VARA. A relevant regulator outside coverage makes
  a result "Could not verify" (U2).

## 4. Data

- **Entity level:** real register and alert entries, strata E1–E11 (§11.2 A). DFSA facts are
  recorded by hand, kept in a restricted store and never released.
- **Message level:** clearly labelled synthetic offers built from the records, factors F1–F15
  (§11.2 B), written as templates, paraphrases by a model from another family, and by people.
  Labels come from the policy engine and are checked blind by two people.
- **Table 1** (`datasets.md`, `datasets.tex`): sizes by split, label, origin and DFSA-derived
  share. Report agreement (Cohen's kappa) from `tessera-eval agreement`.

## 5. Systems

- **The crew:** seven agents on an event-sourced blackboard, typed findings and messages, conflict
  detection C1–C7, a Reconciler that mediates, and a Verifier that can only downgrade, with gates
  G1–G8 (§6). Register lookups are tools, never agents. Evidence is minted only by tools.
- **Baselines:** RULES-ONLY, SA-BASE (mandatory), SA-VER, SA-SC5, SA-MAX, and optionally
  SA-LARGER. **Ablations:** CREW-SILO, CREW-SHARE, CREW-NV (§10.2).
- **Fairness:** the same model, runner, tools, rule cards and guidance; the same number of prompt
  revisions on development data only (`backend/prompts/CHANGELOG.md`); compute reported for all.
- **Model and settings:** the free model, reasoning setting, temperature and pace, from
  `policies/models.yaml` and ADR-0004.

## 6. Evaluation protocol

- **Hypotheses H1–H5**, exactly as registered in `docs/pre-registration.md`.
- **Metrics** (§11.3), with false reassurance as the primary safety metric.
- **Statistics:** paired bootstrap intervals, exact McNemar tests, Holm's correction over the
  secondary family, and the H2 non-inferiority margin (§11.4).
- **Deviations:** every row of the pre-registration's deviations log, with its reason.

## 7. Results

Report the entity level and the message level separately, and report every registered result,
whether it held or not.

- **Table 2** (`results-<level>`): every system, with intervals.
- **Comparisons** (`comparisons-<level>`): H1 and H2, then H3 and H4 with Holm's correction.
- **Figure 3** (`figure-frontier-<level>.svg`): false reassurance beside requests and tokens.
- **H5:** the interaction by factor, from the report's `interaction` block.
- **Stability:** agreement across the temperature-0.7 runs.

## 8. What the mechanisms did

- **Table 3** (`coordination-<level>`): conflicts, challenges, revisions, vetoes, veto precision
  and recall, rescues and conformity flags.
- **Figure 4** (`figure-ablation-<level>.svg`): what sharing, challenges and the Verifier each
  change.
- **Figure 5** (`figure-factors-<level>.svg`): accuracy on each factor or stratum.
- **Failure analysis:** MAST codes on at least 50 crew failures, with kappa between coders, from
  `tessera-eval failure-codes`. Report the share coded outside MAST as well.
- **Cases:** two or three traces from the replay view, chosen by a rule fixed before looking, such
  as the first item of each kind of error.

## 9. Interpretation

Decide which row of implementation-plan.md §17.3 the results support, and use the reading written
there in advance:

- the crew has lower false reassurance, and matched compute does not close the gap;
- the crew equals SA-VER, and both beat SA-BASE: the gain is verification, not the crew;
- the crew equals every single agent: capability saturation, a clean null result;
- the crew helps only the smaller model: coordination stands in for capability;
- the crew is worse: coordination overhead and errors that spread, shown by the failure coding.

## 10. Limitations

- Development numbers came from fictional data and are not reported as results.
- Synthetic messages, however carefully built, are not real messages.
- One free model family, at a free tier's pace, with reasoning on.
- Phase 1 covers three of the five regulators.
- English text only.
- DFSA facts were recorded by hand, at one point in time, and cannot be released.

## 11. Ethics and data governance

The DFSA's terms, and how the code enforces them: hand-recorded facts only, a restricted store,
masking before any model call, no deep links, no public tool. Synthetic messages only, with no real
person's data. No verdict on any firm and no investment advice. What is released and what is not
(implementation-plan.md §17.5), after `tessera-eval release-check` passes.

## Appendices

- A. Rule cards, with sources and their verification status.
- B. Prompts and the revision log.
- C. The pre-registration and its deviations.
- D. The run book, `docs/running-the-evaluation.md`.
- E. The MAST codebook: the 14 modes and the codes outside MAST, from
  `backend/src/tessera/evaluation/failures.py`.

## Where each number comes from

| In the paper | Command | File |
|---|---|---|
| Table 1 | `tessera-eval paper --items ...` | `datasets.md`, `datasets.tex` |
| Table 2, comparisons | `tessera-eval report --out`, then `tessera-eval paper` | `results-<level>`, `comparisons-<level>` |
| Table 3 | `tessera-eval paper` | `coordination-<level>` |
| Figures 3 to 5 | `tessera-eval paper` | `figure-*.svg`, with a CSV beside each |
| Label agreement | `tessera-eval agreement` | printed |
| Failure modes and their kappa | `tessera-eval failure-codes --out` | the summary JSON |
| Requests, tokens and time | `tessera-eval report` | the report's `compute` block |
