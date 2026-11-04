# Data governance

How TESSERA obtains, stores, uses and (never) publishes data. This is the working procedure
behind implementation-plan.md §8, §9 and §12. It is an engineering reading of each source's
terms, not legal advice.

## 1. Principles

1. **No automated access to regulator websites.** The network guard blocks the domains of the
   CMA (and legacy SCA), VARA, DFSA, CBUAE and ADGM in every process.
2. **Manual, low-rate collection only**, by a person in a normal browser.
3. **Facts, not copies.** We record the fields in the templates. We never store pages,
   screenshots or regulator wording.
4. **DFSA values exist in one place:** `data/restricted/dfsa/`. Everything else refers to them by
   row ID. They load only in `RESEARCH_INTERNAL` mode and are masked before any model call.
5. **Nothing real is published.** The GitHub repository is public; real data stays on this
   machine.

## 2. What never leaves this machine

Never commit or push any of the following. `.gitignore` excludes them, and the commit guard
(`scripts/check_restricted.py`, run by `.githooks/pre-commit` and in CI) blocks them even with
`git add -f`:

- `PS.md` (it quotes DFSA alerts);
- `data/inbox/`, `data/handrecords/*.csv`, `data/snapshots/`, `data/restricted/`;
- `datasets/` (except its README), `runs/`, `.env`;
- any deep link into `dfsa.ae` (only `https://www.dfsa.ae/` may appear);
- any API key.

Enable the hook once per clone:

```bash
git config core.hooksPath .githooks
```

## 3. Procedures by source

Record your initials in `recorded_by` or `--retrieved-by`, and the date in `YYYY-MM-DD` format.

### 3.1 CMA Licensed Companies (manual "Export To Excel")

1. In a normal browser, open the CMA Licensed Companies page (the URL is in
   `policies/sources.yaml`).
2. Click **Export To Excel** once. Do not script, refresh repeatedly or probe the site. The CMA
   terms forbid "increasing load to or immersing" it and any weakness testing.
3. Save the file as `data/inbox/cma_licensed/cma_licensed_<date>.xlsx`.
4. Note the page's "last modified" date if it shows one.
5. Ingest it:

   ```bash
   cd backend
   uv run tessera-ingest cma_licensed ../data/inbox/cma_licensed/cma_licensed_2026-11-05.xlsx --retrieved-by KJ --retrieved-on 2026-11-05 --page-last-modified 2026-11-02
   ```

   If the headers are not recognised, copy `data/handrecords/templates/cma_column_map.example.yaml`,
   edit it, and add `--column-map <file>`.

### 3.2 CMA Warnings (hand-recorded)

1. Open the CMA Warnings page in a normal browser.
2. For each warning in scope (all 2026 warnings, plus recent ones if useful), fill in one row of
   `templates/cma_warnings.csv`. Save the file as `data/handrecords/cma_warnings.csv`.
3. Ingest it with `uv run tessera-ingest cma_warnings ../data/handrecords/cma_warnings.csv --retrieved-by KJ --retrieved-on <date>`.

### 3.3 VARA Public Register and Unlicensed VASPs (hand-recorded, low rate)

1. One browser session. Open entries one at a time, at a human pace, with no tab flooding.
2. Fill in `templates/vara_register.csv`. Set `status` to `LICENSED` or `IPA`, never mixing them,
   and copy the licensed activities exactly as listed.
3. Fill in `templates/vara_unlicensed.csv` (38 entries per PS.md).
4. Save both under `data/handrecords/`, then ingest them with source IDs `vara_register` and
   `vara_unlicensed`.
5. VARA's terms allow personal non-commercial use and forbid publishing or distributing its
   material. These files therefore stay local, and any public release uses rehydration recipes.

### 3.4 DFSA (hand-recorded facts, restricted)

1. **First**, read the full DFSA Legal Disclaimer in a browser. It is reached from the footer of
   `https://www.dfsa.ae/`.
2. Record facts **only for the firms and 2026 alerts used in evaluation**, using
   `templates/dfsa_register_facts.csv` and `templates/dfsa_alert_facts.csv`.
3. Use our own category labels. Do not copy DFSA text, do not take screenshots, and do not record
   any DFSA link.
4. Save the files as `data/restricted/dfsa/register_facts.csv` and
   `data/restricted/dfsa/alert_facts.csv`.
5. Ingest in research mode. The command refuses DFSA files outside `data/restricted/`:

   ```bash
   cd backend
   TESSERA_MODE=RESEARCH_INTERNAL uv run tessera-ingest dfsa_register ../data/restricted/dfsa/register_facts.csv --retrieved-by KJ --retrieved-on 2026-11-06
   ```

   In PowerShell, set the variable first: `$env:TESSERA_MODE = "RESEARCH_INTERNAL"`.

## 4. Operating modes

| Mode | DFSA data | Use for |
|---|---|---|
| `RESTRICTED_DEMO` (default) | Never loads; the DFSA agent answers "manual check required at www.dfsa.ae" | Screenshots, talks, anything shown to others |
| `RESEARCH_INTERNAL` | Loads from `data/restricted/`; masked before any model call | Local research and evaluation |

## 5. Model providers

Models run on NVIDIA's free API catalog, whose free endpoints may record inputs and outputs. So:

- only synthetic offer text, public CMA and VARA facts, placeholders, and relations the tools
  work out are sent. A relation says something about a masked firm in our own terms: its status,
  its zone, which of our activity codes its recorded services cover, or an alert's category;
- the masking gateway replaces every identifying DFSA value, including street-level address
  parts, with a placeholder such as `⟦R:FIRM-1⟧` before a request leaves the machine, and an
  invariant test fails if any value slips through;
- recorded services and alert dates are never sent. A second test checks them against every
  outgoing request and the event log. If a recorded service is not understood, the tool reports
  scope as unknown, so extend `dfsa_terms` in `knowledge/taxonomy/activities.yaml` with our own
  short terms, never with copied DFSA text;
- no personal data is ever used.

A DFSA alert's date appears only in a report, built on demand in `RESEARCH_INTERNAL` mode. It is
never sent to a model, and never written to the event log.

## 6. Purge procedure

To remove all DFSA data: delete `data/restricted/` and `datasets/restricted/`. Nothing else holds
DFSA values. Delete `runs/` as well: it keeps row references and masked relations, which should
not outlive the facts. The system keeps working, and DFSA-dependent results become "Could not
verify".

## 7. Release checklist (before sharing any artefact)

- [ ] No file from §2 is included.
- [ ] No DFSA value, DFSA wording or DFSA deep link appears.
- [ ] No VARA material is copied verbatim. Entity-level data ships only as rehydration recipes.
- [ ] Every synthetic message is labelled `synthetic: true`.
- [ ] Screenshots were taken in `RESTRICTED_DEMO` mode.

## 8. If something restricted is committed by mistake

- **Not yet pushed:**
  1. Undo the commit with `git reset --soft HEAD~1`.
  2. Unstage the file and fix `.gitignore`.
  3. Commit again.
- **Already pushed to the public repository:** treat the material as published.
  1. Revoke any exposed key immediately.
  2. Rewrite history to remove the file, then force-push. Only do this after agreeing it with
     the repository owner.
  3. Record what happened in the decision log.
