# Running the evaluation

The steps from an empty `data/` folder to the final report, in order. Commands run from `backend/`.
`tessera-eval readiness` shows at any point what is still missing.

## 1. Collect the records by hand

Follow `data/README.md` and `data/handrecords/README.md`. Nothing here downloads regulator data, and
DFSA pages are never fetched by any tool.

| Source | How | Where it goes |
|---|---|---|
| CMA licensed companies | The manual "Export To Excel" button | `data/inbox/cma_licensed/` |
| CMA warnings | Copy into the template by hand | `data/handrecords/cma_warnings.csv` |
| VARA public register | Copy into the template by hand, at a low rate | `data/handrecords/vara_register.csv` |
| VARA unlicensed list | Copy into the template by hand | `data/handrecords/vara_unlicensed.csv` |
| DFSA register and alerts | Record the template's fields by hand, and nothing else | `data/restricted/dfsa/` |
| CBUAE-only firms (optional, E10) | A list of names, one per line | A local file you pass to `entities` |

Then ingest each file:

```bash
uv run tessera-ingest cma_licensed ../data/inbox/cma_licensed/export.xlsx --retrieved-by KJ --retrieved-on 2026-11-05
```

## 2. Check what is missing

```bash
uv run tessera-eval readiness
```

## 3. Build the datasets

```bash
uv run tessera-eval entities --out ../datasets/entity_level --cbuae-names ../data/cbuae_names.txt
uv run tessera-eval messages --paraphrase --people --out ../datasets/message_level
```

`messages --paraphrase` takes about 30 minutes for 240 messages at the free tier's pace. Items built
from DFSA facts, and anything else holding those values, go to `datasets/restricted/`. Deleting that
folder and `data/restricted/` removes every DFSA value.

## 4. Write the human share

Fill in the `text` column of `briefs.csv`, in both `datasets/message_level/` and
`datasets/restricted/message_level/`, then bring each one in:

```bash
uv run tessera-eval written --briefs ../datasets/message_level/briefs.csv --out ../datasets/message_level
```

Each message passes the same checks as generated ones, and any that fail are listed.

## 5. Review the labels

See `docs/annotation-guidelines.md`. In short: export a blind sheet per annotator, compare them, and
settle every disagreement.

```bash
uv run tessera-eval sheet --items ../datasets/message_level/dev/items.jsonl --annotator A --out ../datasets/review/A.csv
uv run tessera-eval agreement --items ../datasets/message_level/dev/items.jsonl --first ../datasets/review/A.csv --second ../datasets/review/B.csv
uv run tessera-eval settle --items ../datasets/message_level/dev/items.jsonl --decisions ../datasets/review/decisions.csv
```

`decisions.csv` has the columns `item_id,label`. A blank label drops the item, and every drop is
listed. Do the same for the test items, and keep sheets for restricted items under
`datasets/restricted/`.

## 6. Check the set on the development split

```bash
uv run tessera-eval probe --items ../datasets/message_level/dev/items.jsonl
uv run tessera-eval leakage
uv run tessera-eval components --items ../datasets/message_level/dev/items.jsonl
```

If plain rules score too high, the messages are too easy, so make them harder before going on.

## 7. Tune prompts on development data only

Each system gets the same number of revisions, at most 5, logged in `backend/prompts/CHANGELOG.md`.
A prompt change is a new configuration, so use a new run folder each time.

## 8. Run the pilot

```bash
uv run tessera-eval run --items ../datasets/message_level/dev/items.jsonl --limit 20 --run-dir ../runs/eval/pilot --parallel 3
uv run tessera-eval report --items ../datasets/message_level/dev/items.jsonl --run-dir ../runs/eval/pilot
```

Use the measured requests per case to update `implementation-plan.md` §11.5, and the measured rates
to redo the power check:

```bash
uv run tessera-eval power --baseline 0.10 --crew 0.04
```

If the run is too long, apply the fallback order in `docs/pre-registration.md`. The primary
comparison is never cut.

## 9. Freeze

```bash
uv run tessera-eval freeze --items ../datasets/message_level/test/items.jsonl ../datasets/restricted/message_level/test/items.jsonl --out ../datasets/freeze-message.json
uv run tessera-eval freeze --items ../datasets/entity_level/test/items.jsonl ../datasets/restricted/entity_level/test/items.jsonl --out ../datasets/freeze-entity.json
```

A freeze records the test set with the prompts, policies, knowledge, plan and model settings. After
this, finish `docs/pre-registration.md`: it is frozen too, and any later change goes in its
deviations log.

## 10. Run the test sets

```bash
uv run tessera-eval run --items ../datasets/message_level/test/items.jsonl ../datasets/restricted/message_level/test/items.jsonl --frozen ../datasets/freeze-message.json --run-dir ../runs/eval/message --parallel 3 --hours 10
```

Run the same command each night until it reports nothing left, and do the same for the entity level
with `--no-stability`. Test items need a matching freeze. A run also pins its configuration and date
when it starts, and refuses a session that differs, so results cannot mix.

A case the provider cut short is not kept as a result. It runs again next session, and an outage
stops the run after three failures in a row.

## 11. Report

```bash
uv run tessera-eval report --items ../datasets/message_level/test/items.jsonl ../datasets/restricted/message_level/test/items.jsonl --split test --run-dir ../runs/eval/message --out ../runs/eval/message-report.json
```

Entity-level and message-level results are reported separately, and all of them are reported,
whether a hypothesis held or not.

## Filling the Lab

The Lab is built from two files in `frontend/src/data`. Both hold totals and no item text.

```bash
uv run tessera-eval lab --fiction --items <messages.jsonl> --run-dir <run folder> \
  --out ../frontend/src/data/pilot-comparison.json \
  --report ../frontend/src/data/pilot-report.json
```

The final numbers go in `evaluation.json` the same way, with `tessera-eval report --out`
after the release review. Entity-level results come from real records, so read the Data Governance
document before committing anything built from them.
