# Data folder

Real data never leaves this machine. Only this README and `handrecords/templates/` are
committed; everything else here is git-ignored and blocked by the commit guard.

| Folder | What goes there | Who writes it |
|---|---|---|
| `inbox/<source_id>/` | Files you downloaded by hand, such as the CMA "Export To Excel" file | You |
| `handrecords/` | CSV files you filled in from the templates (CMA warnings, VARA) | You |
| `restricted/dfsa/` | DFSA hand-recorded facts. Loaded only in `RESEARCH_INTERNAL` mode | You |
| `snapshots/<source_id>/<snapshot_id>/` | Immutable normalised snapshots and manifests | `tessera-ingest` |
| `restricted/snapshots/…` | Snapshots of restricted (DFSA) sources | `tessera-ingest` |

Rules, in short (details in `docs/data-governance.md`):

- No automated access to any regulator website. The code blocks it.
- CMA: use the manual "Export To Excel" button only.
- VARA: copy by hand at a low rate, in one browser session.
- DFSA: record only the template fields, by hand. No copies of pages, no screenshots, no DFSA
  wording, and no link other than the homepage, `https://www.dfsa.ae/`.
- Deleting `restricted/` removes every DFSA value. The system still runs; DFSA cases become
  "Could not verify".
