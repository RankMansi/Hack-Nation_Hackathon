# Rental Housing Law Navigator

For any of the 500 supplied apartment addresses and a date, this FastAPI demo
shows state/city rules, exact source text, retrieval date, explanation and
uncertainty. **Not legal advice or a compliance certification.**

## Reproduce this submission

The imported raw pack, model responses, Census responses and targeted public
supplements are already included. A normal rebuild makes **zero paid model
calls** and uses cached jurisdiction resolution. Do not replace `data/raw/`.

```bash
uv sync --frozen
ANTHROPIC_MODEL=claude-sonnet-4-5 uv run --frozen python -m src.pipeline
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen python -m src.check
uv run --frozen python scripts/build_method_note.py
```

The pipeline fails clearly if model caches are missing; configure credentials
through **Replit Secrets**, not source files. `--refresh` deliberately regenerates
paid extraction and is not needed for reproduction. A completely fresh geocoder
cache requires public Census network access. Keep the supplied cache for the
same reproducible jurisdiction results.

## Live demo

Use Replit's **Run** button, or the existing workflow command:

```bash
uv run uvicorn src.web:app --host 0.0.0.0 --port 5000
```

Select a sample building and date. The demo reads internal historical rules, not
the deliberately minimal current submission. It makes no model or geocoder
calls. Date changes distinguish pending, not-yet-effective and ended provisions.
Malformed dates and unknown address IDs return explicit errors.

- `/`: building/date selector, grouped explanations, source quotes, human-review
  flags and source limitations.
- `/api/lookup/A0001?as_of=2026-10-01`: the same evaluator with joined rule evidence.
- `/method-note`: one-page method note PDF.
- `/downloads/rules.json`, `/downloads/lookups.json`,
  `/downloads/changes.json`: required submission files.
- `/downloads/source_inventory.json`, `/downloads/validation.json`: source
  disclosures and local validation evidence.

Try a Los Angeles building before/after 2024-01-31 to see the moratorium end;
California on 2025-12-31 / 2026-01-01; New Jersey on 2026-10-01 / 2027-07-01;
Hoboken versus Jersey City versus Newark; and either Massachusetts city for
both pending bills without an enacted rent cap.

## Submission and audit

| File | Purpose |
|---|---|
| `outputs/rules.json` | Published schema fields only; current/known future and non-enacted rules; no ended records |
| `outputs/lookups.json` | Exactly 500 IDs, default `2026-10-01`, only five permitted results and four template answer fields |
| `outputs/changes.json` | Exactly T1–T5, affected IDs, conflict IDs, notes |
| `outputs/rules_internal.json` | Inclusive operative intervals, historical versions, stable IDs, retrieval, penalties, evidence and derivations |
| `outputs/lookups_internal.json` | Each answer joined to its quote, URL, retrieval/as-of date and evidence |
| `outputs/changes_internal.json` | Separate local boundary sets, matched rules and date-transition diagnostics |
| `outputs/audit.jsonl` | Proposed records, rejection reasons, exact-quote recoveries, deterministic repairs and merges |
| `outputs/source_inventory.json` | Every missing/link-only raw source and all supplemental URLs, retrieval times and hashes |
| `outputs/validation.json` | Automated published-requirement checks, explicitly not an official score |
| `outputs/failures.txt`, `outputs/unresolved-addresses.txt` | Extraction failures and unresolved addresses |

`data/supplemental/` is separate from the unchanged raw pack. Its manifest
records targeted public web/PDF captures, the extraction method and SHA-256
hashes. These are captured text (including markdown formatting), not invented
corpus quotations. Deterministic grammars extract the adopted New Jersey local
bans, published San Diego effective day, Massachusetts failed petition
disposition and LA annual-rate history. Captures are fixed inputs for
reproduction; normal runs do not silently refetch or bulk-scrape websites.

## Method and limits

- **A: extract.** Cached structured model extraction is revalidated against
  exact source slices and citation identifiers. Non-operative headings and
  employment-only provisions are rejected. Duplicate laws prefer codified
  official evidence only for equivalent obligations and coverage; distinct
  statutory duties, coverage branches and time intervals are retained.
- **B: resolve/apply.** Census incorporated-place geography, not mailing city,
  determines city rules. Assessor year is only a construction-year proxy:
  cutoff-year, owner, use, subsidy, registration, rehabilitation and missing
  unit facts remain unknown as warranted. Known conflicting unit descriptions
  are flagged. County geography is shown, but county rules are out of scope.
- **C: changes.** T1–T5 are computed from the evaluator and supplied case
  definitions, never hand-listed address IDs. Possible NJ state/local
  preemption appears in both change tracking and current/future lookups.
- **Dates.** Inclusive ends stop governing the next day. Public commencement
  authority is a separate supporting source with an explicit derivation;
  the resulting date is never passed off as a corpus quote. Amendment footers
  are not assumed to be the birth date of unchanged provisions.

The pack has 54 available documents and 33 missing/link-only entries. Twelve
targeted supplemental captures close specific gaps, **not all missing laws**.
Seven addresses remain legally city-unresolved and receive state-only answers,
not inferred local rules. Hoboken's publication-dependent exact start and its
inconsistent section headings, Jersey City's precise commencement (a later
adopted amendment establishes an in-force-by anchor of 2025-09-24), and the
start of Berkeley's amended algorithmic ban remain disclosed source
uncertainties. The Berkeley historical answer is unknown before the captured
current version. Unsupported old statutory versions are not invented.

See [`docs/requirements.md`](docs/requirements.md) for the published-requirement
checklist and [`docs/method-note.md`](docs/method-note.md) for the one-page note.
No official `score.py`/answer key is supplied, so no hidden scoring outcome is
claimed.

## Optional incoming documents

Hour-16 surprise documents are **not part of this participant pack**. Existing
incoming tooling is opt-in:

```bash
uv run python -m src.pipeline --include-incoming
```

It may need a paid extraction call for a new document. New rules and diagnostics
stay internal; required files still exclude incoming rules and export only
T1–T5. Never use this flag to change the required submission.

All work remains in this Replit workspace. Do not push to GitHub, create a pull
request, deploy, replace the raw pack, or change the stack without a new request.