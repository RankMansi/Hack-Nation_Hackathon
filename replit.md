# Rental Housing Law Navigator

## Run on Replit

Use the **Run** button to start the `Start application` workflow. It runs:

```bash
uv run uvicorn src.web:app --host 0.0.0.0 --port 5000
```

The existing FastAPI app serves the HTML interface and evaluates housing rules for the selected building and date. Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

## Data and optional extraction

The web interface reads `outputs/rules_internal.json` and `data/cache/stacks.json` without calling Anthropic or Census. Internal history is intentionally separate from minimal submission files. No API key is required to use the demo.

Regenerating outputs is a separate operation. Valid model/geocoder caches are included, so a normal rebuild requires no key and makes no paid model calls:

```bash
uv run python -m src.pipeline
```

Use `--refresh` only when intentionally re-extracting every document. Extraction can incur API charges and rewrites the generated outputs. Never put credentials in source files.

Uncached extraction needs `ANTHROPIC_API_KEY` through Replit Secrets. Do not regenerate paid responses blindly. `--include-incoming` is optional and cannot alter required exports.

## Project constraints and verification

- Keep the existing Python/FastAPI structure and preserve `data/raw/`.
- Make changes only in this Replit project. No GitHub push, pull request or deployment without a new user request.
- Required exports contain only T1–T5 and use the supplied schema/template fields.
- Rebuild: `uv run python -m src.pipeline`; regression tests: `uv run python -m unittest discover -s tests -v`.
- The pipeline writes `outputs/validation.json`; these are local checks, not an unavailable official scorer.
- Rebuild the one-page note with `uv run python scripts/build_method_note.py`.

This tool is not legal advice. See `README.md`, `docs/requirements.md` and the one-page method note for methodology and remaining source/fact limitations.