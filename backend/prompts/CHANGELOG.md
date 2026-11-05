# Prompt revisions

The fairness contract (implementation-plan.md §10.1) gives the crew and the single agent the same
tuning budget: at most 5 revisions each, and the same number for both, on development data only.
Prompts are frozen before any test run. A revision is one change made after looking at a system's
results, so fixes to the code around the prompts do not count.

| Revision | System | Date | What changed | Why |
|---|---|---|---|---|
| 1 | Crew | 4 Nov 2026 | `Reconciler` claims must cite evidence. `Jurisdiction` lists the values of `basis` | First live case on the fictional smoke set |
| 2 | Crew | 4 Nov 2026 | Example evidence IDs replaced with a placeholder. Reply format shown with an example. Advice added on when there is no register match, on payment instructions, on checking HC1 to HC6 in turn, and on what counts as a contradiction | First full live run on the fictional smoke set |
| 3 | Crew | 5 Nov 2026 | `Verifier` told that an alert naming a firm as the victim is no contradiction when contacts match. Ground rules ask for "official" over "legitimate" | Second full live run on the fictional smoke set |

| 4 | Crew | 5 Nov 2026 | `SEC.PROMOTION` in the shared activity list now says it means promoting another firm's products for a fee | A firm's own advertising was read as an activity outside its licence. The list is shared knowledge, so the single agent gets the same wording |

**Crew: 4 revisions. Single agent: 0.** The single agent's prompt was written after revision 3 and
shares the crew's guidance files, so it starts from the same knowledge. It must get the same number
of revisions as the crew before prompts are frozen.
