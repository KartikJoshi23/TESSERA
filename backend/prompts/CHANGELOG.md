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
| 5 | Crew | 5 Nov 2026 | The starting matrix's Unknown row and a new line in the shared `_jurisdiction_guide`: a free-zone regulator needs a sign of its zone. New rule card SCOPE-CMA-03, and a line in the shared `regulator_cma`, for CMA scope in any category | First look at the harder fictional set. With no zone signal the matrix made FSRA relevant, so a confirmed firm could never be Consistent. The CMA cards covered only Category 5, so a correct scope conclusion on another category had no card to cite. Both are shared, so the single agent gets the same wording |
| 1 | Single agent | 5 Nov 2026 | Only CMA, DFSA and VARA go in `regulators`. Cite only a card that fits the licence. A warning or alert record is not a register match | Its own runs on the harder set and the looping cases: CBUAE and FSRA in `regulators` cost a repair on two cases, a Category 5 card was cited for a Category 1 and a Category 2 firm, and an alert record was sent to `official_contacts_for` |

All fictional data is development data. The test set is built from real records and nobody has seen it.

**Crew: 5 revisions, which is the limit. Single agent: 1.** The single agent's prompt was written
after revision 3 and shares the crew's guidance files, so it starts from the same knowledge. It must
get the same number of revisions as the crew before prompts are frozen, each from a look at its own
results.
