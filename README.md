# Rental Housing Law Navigator

For a sample apartment address and an as-of date, this shows which state and city housing rules apply, with the citation, the quoted line from the law, and its retrieval date. **Not legal advice.**

## Setup

1. Unzip the RealPage starter pack into `data/raw/` (so `data/raw/corpus/corpus_manifest.csv` exists). The raw pack is never modified.
2. `cp .env.example .env` and set `ANTHROPIC_API_KEY` (optionally `ANTHROPIC_MODEL`).
3. Install [uv](https://docs.astral.sh/uv/). Dependencies install on first run.

## Commands

```bash
uv run --env-file .env python -m src.pipeline            # geocode (cached), extract (cached), write outputs, self-check
uv run --env-file .env python -m src.pipeline --refresh  # re-extract every document with the model
uv run python -m src.web                                 # http://127.0.0.1:8000
```

Outputs: `outputs/rules.json`, `outputs/lookups.json` (all 500 addresses, as of 2026-10-01), `outputs/changes.json` (T1–T6), plus `audit.jsonl` (every proposed rule, kept or dropped with the reason), `failures.txt`, `unresolved-addresses.txt`.

**Hour-16 ordinance:** drop the plain-text file into `data/incoming/` and rerun the pipeline. It goes through the same extraction and apply path and is reported as T6. No code change.

## How it works

- **Extract (Module A).** One structured tool call per corpus document (link-only rows are skipped). The model proposes rule records; code keeps a rule only if its quote is found in the source file (whitespace and quote characters normalized) and its citation numbers appear in that file. The stored `quoted_span` is the slice taken from the file, not the model's text. Raw model responses are cached in `data/cache/extract/`, keyed by document hash, model and prompt version.
- **Resolve (Module B).** Address matching is code: one Census batch geocode (`Public_AR_Current`), then the Census coordinates lookup for state, county and incorporated place. The postal city is never used to pick the legal city, so Van Nuys resolves to Los Angeles and Dorchester to Boston. Unmatched addresses get state rules only and are listed.
- **Apply.** `src/apply.py` is a pure function of rules, the cached jurisdiction stack, building facts and the as-of date. Missing year built or units become `unknown`. A building in a certificate-of-occupancy cutoff year is `unknown`. A state rule whose text yields to local law becomes `superseded` where a local rule applies. A pending or not-yet-effective state rule next to an applying local rule raises a conflict flag.
- **Changes (Module C).** Each test in `dev/change_tests.json` is `apply` at one or two dates followed by a difference.
- **Self-check.** The participant pack ships without `score.py`, so `src/check.py` verifies the schema, quote grounding, all 500 addresses, and the T1–T5 expectations after every run.

Known corpus gaps: the Hoboken and Jersey City algorithmic-ban texts and the Massachusetts ballot-question source are link-only in the pack. They are not extracted. T2 and T3 report the Census boundary sets for those cities with a note saying so.

New jurisdictions: add their documents to the manifest and their names to `src/config.py`. The prompt, grounding and apply logic are jurisdiction-agnostic.
