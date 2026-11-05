# Pre-registration

**Status: draft, not frozen.** It is frozen once the real test sets exist, the pilot has run and the
prompts are final. After that, any change goes in the deviations log at the end, with its reason.

What runs is `eval/plan.yaml`. Every result record holds a hash of that file, so a change after the
freeze can be seen. The full reasoning is in `implementation-plan.md` §10 and §11.

## Question

Does a crew of agents that share structured findings, challenge each other and answer to a Verifier
give fewer false reassurances than one agent with the same model, tools and knowledge?

A single agent doing as well is a valid result, and it will be reported as one.

## Hypotheses

| ID | Claim | Test |
|---|---|---|
| H1 (primary, safety) | CREW-FULL's false-reassurance rate is lower than SA-BASE's on the message-level test set | Exact McNemar on per-item false reassurance, with a paired bootstrap 95% interval on the difference |
| H2 (primary, usefulness) | CREW-FULL's macro-F1 is no more than 2 points below SA-BASE's | Non-inferiority: the lower end of the paired bootstrap interval must sit above -0.02. Coverage is reported beside it |
| H3 | Sharing and challenges each help, and the Verifier helps inside the crew | CREW-SHARE against CREW-SILO, CREW-FULL against CREW-SHARE, CREW-FULL against CREW-NV. Holm-Bonferroni over the family |
| H4 | The gain survives equal compute | CREW-FULL against SA-SC5 and SA-MAX on false reassurance, in the same family |
| H5 | The gain sits in copied-identifier, cross-jurisdiction and scope cases (F1, F6, F7) | Interaction test by factor |
| H6 (optional) | The gain shrinks as the model gets stronger | Crew-against-single difference on the smaller model against the primary model |

Everything else broken down by factor is exploratory, and is labelled that way.

## Data

- **Message level:** 480 labelled synthetic offers, 160 per result, 30% development and 70% test.
  About 30% come from templates, 50% from paraphrase by a model of a different family, and 20% are
  written by people.
- **Entity level:** about 280 to 360 cards built from real register and alert records, strata E1 to
  E11, with the same split. Strata are small, so per-stratum results are case studies.
- The two levels are analysed separately and never pooled.
- The test split stays sealed: it is not used to tune prompts or thresholds.
- Labels come from the decision-policy engine and are then checked by people who cannot see them.
  Cohen's kappa must reach 0.8, or the single-annotator fallback applies: everything labelled twice,
  at least two weeks apart.
- A set is frozen by writing its content hash (`tessera-eval freeze`).

## Measures

- **Primary:** false-reassurance rate, P(prediction = Consistent | gold ≠ Consistent), and macro-F1.
- **Safety:** unsupported-conflict rate, also reported on gold Consistent alone, because that is the
  risk of wrongly implicating a genuine firm.
- **Guards against abstaining:** coverage and decisive accuracy.
- **Summary:** cost-weighted error under the fixed matrix in §11.3.
- **Mechanisms:** conflicts, challenges, revisions, veto precision, veto recall and rescue rate.
- **Cost:** requests, tokens and time per case.

## Decisions fixed in advance

- **Decoding:** one primary run per condition at temperature 0 with a fixed seed.
- **Stability:** temperature 0.7, SA-VER and CREW-FULL three runs each. SA-SC5's five samples serve
  as SA-BASE's.
- **Reasoning setting:** on, the model's default, for every condition. On or off is the model's only
  control, so SA-MAX differs from SA-BASE only in its longer output allowance. SA-SC5 is the arm that
  spends the extra compute in a different way.
- **A system that gives no result** is scored as "Could not verify", and failures are reported.
- **Prompts:** the same number of revisions for both systems, at most 5 each, on development data
  only, logged in `backend/prompts/CHANGELOG.md`.

## If the free tier runs short

The primary comparison is never cut. Fallbacks apply in this order, and each use is logged:

1. SA-VER stability runs drop to 2.
2. Stability runs cover a stratified half of the message-level test set.
3. The optional capability arm is dropped.

## Deviations

Each entry gives the date, what changed and why.

| Date | Change | Why |
|---|---|---|
| 2026-11-05 | Pace set to 7.5 requests a minute, not 35 | Measured with no retries: about 8 a minute get through on this free key. A full run takes about a week, not 45 hours (§11.5) |
| 2026-11-05 | SA-MAX defined as SA-BASE with twice the output allowance | The plan assumed a higher reasoning setting, but the model only offers on or off, and on is the default for all. 32,768 tokens a reply covers the crew's median output of about 27K tokens a case. Only 1 of 136 single-agent replies reached the normal allowance, so SA-MAX may differ little from SA-BASE |
